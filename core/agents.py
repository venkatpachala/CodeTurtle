from langchain_core.prompts import ChatPromptTemplate
from core.llm import get_llm
from core.state import ReviewState
from pydantic import BaseModel, Field
from typing import List


class CodeReviewFindings(BaseModel):
    bugs: List[str] = Field(default_factory=list, description="List of bugs or potential issues")
    architecture_issues: List[str] = Field(default_factory=list)
    security_concerns: List[str] = Field(default_factory=list)
    testing_gaps: List[str] = Field(default_factory=list)
    positives: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class ReviewOutput(BaseModel):
    summary: str
    findings: CodeReviewFindings
    recommendation: str = Field(..., description="MERGE, REQUEST_CHANGES, or COMMENT")
    confidence: float = Field(..., ge=0, le=1)


def context_summarizer(state: ReviewState) -> ReviewState:
    """Summarizes the raw context retrieved from knowledge base"""
    llm = get_llm(temperature=0.2, max_tokens=600)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a helpful assistant that summarizes technical context from a codebase.
Create a concise summary of the provided code/documentation that is relevant to the current Pull Request.
Focus on key functions, classes, architecture patterns, and logic that the PR is likely modifying or extending.
Keep the summary short and focused."""),
        ("human", """PR Title: {title}

Raw context from knowledge base:
{raw_context}

Please provide a concise summary of the relevant codebase context.""")
    ])

    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "raw_context": state.context_from_kb
    })

    state.summarized_context = response.content
    state.traces.append({
        "agent": "ContextSummarizer",
        "output": response.content
    })
    return state


def context_gatherer(state: ReviewState) -> ReviewState:
    llm = get_llm(temperature=0.3, max_tokens=800)

    previous_context = ""
    if state.previous_reviews:
        previous_context = "\n\nPrevious reviews of this repository:\n"
        for rev in state.previous_reviews:
            previous_context += f"- PR #{rev['number']}: {rev['recommendation']} | {rev['summary'][:200]}...\n"

    context_to_use = state.summarized_context if state.summarized_context else state.context_from_kb

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert Context Gatherer for GitHub code reviews.
You have access to summarized context from the repository knowledge base and previous reviews."""),
        ("human", """Current PR Title: {title}
PR Description: {body}
Author: {author}

Relevant summarized context from repository:
{context_to_use}

{previous_context}

Please provide a clear summary of what this PR is trying to achieve and what areas the Code Reviewer should focus on.""")
    ])

    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "body": state.body,
        "author": state.author,
        "context_to_use": context_to_use,
        "previous_context": previous_context
    })

    state.context_summary = response.content
    state.traces.append({
        "agent": "ContextGatherer",
        "output": response.content,
        "timestamp": str(state.created_at)
    })
    return state


def code_quality_reviewer(state: ReviewState) -> ReviewState:
    llm = get_llm(temperature=0.2, max_tokens=1200)

    context_to_use = state.summarized_context if state.summarized_context else state.context_from_kb

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior Code Quality Reviewer.
Return structured findings only."""),
        ("human", """PR Title: {title}

Relevant summarized context from the repository:
{context_to_use}

PR Code Changes (Diff):
{diff}

Provide structured code quality findings.""")
    ])

    structured_llm = llm.with_structured_output(ReviewOutput)
    response = structured_llm.invoke({
        "title": state.title,
        "context_to_use": context_to_use,
        "diff": state.full_diff or state.diff or "No diff available"
    })

    state.code_analysis = response.model_dump_json(indent=2)
    state.traces.append({
        "agent": "CodeQualityReviewer",
        "output": state.code_analysis,
        "timestamp": str(state.created_at)
    })
    return state


def critic_agent(state: ReviewState) -> ReviewState:
    llm = get_llm(temperature=0.2, max_tokens=1000)

    previous_context = ""
    if state.previous_reviews:
        previous_context = "\n\nNote: Previous reviews of this repo exist in this session."

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Code Review Critic.
Return structured critique."""),
        ("human", """PR Title: {title}

Context Summary:
{context_summary}

Code Quality Analysis:
{code_analysis}

{previous_context}

Please critique the above analysis and suggest improvements.""")
    ])

    structured_llm = llm.with_structured_output(ReviewOutput)
    response = structured_llm.invoke({
        "title": state.title,
        "context_summary": state.context_summary,
        "code_analysis": state.code_analysis,
        "previous_context": previous_context
    })

    state.critique = response.model_dump_json(indent=2)
    state.traces.append({
        "agent": "Critic",
        "output": state.critique
    })
    return state


def final_recommender(state: ReviewState) -> ReviewState:
    llm = get_llm(temperature=0.3, max_tokens=1500)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior maintainer giving the final review decision.
Return structured recommendation."""),
        ("human", """PR Title: {title}
Author: {author}

Context Summary:
{context_summary}

Code Analysis:
{code_analysis}

Critique:
{critique}

Please give your final recommendation and a ready-to-post GitHub comment.""")
    ])

    structured_llm = llm.with_structured_output(ReviewOutput)
    response = structured_llm.invoke({
        "title": state.title,
        "author": state.author,
        "context_summary": state.context_summary,
        "code_analysis": state.code_analysis,
        "critique": state.critique
    })

    state.final_comment = response.model_dump_json(indent=2)
    state.traces.append({
        "agent": "FinalRecommender",
        "output": state.final_comment
    })
    return state