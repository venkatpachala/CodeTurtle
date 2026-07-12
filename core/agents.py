from langchain_core.prompts import ChatPromptTemplate
from core.llm import get_llm
from core.state import ReviewState


def context_gatherer(state: ReviewState) -> ReviewState:
    """Agent that gathers context using repository knowledge base + previous reviews"""
    llm = get_llm(temperature=0.3, max_tokens=800)

    # Format previous reviews
    previous_context = ""
    if state.previous_reviews:
        previous_context = "\n\nPrevious reviews of this repository in this session:\n"
        for rev in state.previous_reviews:
            previous_context += f"- PR #{rev['number']}: {rev['recommendation']} | {rev['summary'][:250]}...\n"

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert Context Gatherer for GitHub code reviews.
You have access to:
- Relevant code from the repository knowledge base
- Previous reviews of this repository in the current session

Your job is to analyze the current PR in the context of the existing codebase and past reviews.
Be concise but insightful."""),
        ("human", """Current PR Title: {title}
PR Description: {body}
Author: {author}

Relevant code from repository knowledge base:
{summarized_context}

{previous_context}

Please provide a clear summary of what this PR is trying to achieve and what areas the Code Reviewer should focus on.""")
    ])

    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "body": state.body,
        "author": state.author,
        "summarized_context": state.summarized_context,
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
    """Agent that reviews code quality using repository knowledge"""
    llm = get_llm(temperature=0.2, max_tokens=1200)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior Code Quality Reviewer.
You have access to relevant parts of the existing codebase through the knowledge base.
Focus on:
- How the new code integrates with existing patterns in the repository
- Potential bugs, regressions, or edge cases
- Code style and best practices used in this specific project
- Test coverage and missing scenarios
Be constructive and specific."""),
        ("human", """PR Title: {title}

Relevant code from the repository knowledge base:
{summarized_context}

PR Code Changes (Diff):
{diff}

Please provide a detailed code quality analysis. Reference existing code patterns where relevant.""")
    ])

    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "summarized_context": state.summarized_context,
        "diff": state.diff or "No diff available (issue review)"
    })

    state.code_analysis = response.content
    state.traces.append({
        "agent": "CodeQualityReviewer",
        "output": response.content,
        "timestamp": str(state.created_at)
    })
    return state


def critic_agent(state: ReviewState) -> ReviewState:
    """Critic agent that reviews the previous agents' work"""
    llm = get_llm(temperature=0.2, max_tokens=1000)

    # Format previous reviews for critic
    previous_context = ""
    if state.previous_reviews:
        previous_context = "\n\nNote: Previous reviews of this repo in this session exist. Consider consistency with past feedback."

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Code Review Critic.
Your job is to review the outputs of the previous agents and improve them.
Check for:
- Missing important issues
- Incorrect or weak analysis
- Lack of specificity
- Poor reasoning
- Inconsistency with previous reviews of this repository (if any)

Be direct and constructive."""),
        ("human", """PR Title: {title}

Context Summary:
{context_summary}

Code Quality Analysis:
{code_analysis}

{previous_context}

Please critique the above analysis and suggest improvements.""")
    ])

    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "context_summary": state.context_summary,
        "code_analysis": state.code_analysis,
        "previous_context": previous_context
    })

    state.critique = response.content
    state.traces.append({
        "agent": "Critic",
        "output": response.content
    })
    return state


def final_recommender(state: ReviewState) -> ReviewState:
    """Final agent that gives recommendation and generates comment"""
    llm = get_llm(temperature=0.3, max_tokens=1500)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior maintainer giving the final review decision.
Based on all previous analysis (including context from the repository knowledge base and past reviews), give:
1. A clear recommendation: MERGE, REQUEST_CHANGES, or COMMENT
2. A professional, constructive comment that can be posted on GitHub.

Be balanced, specific, and consistent with previous feedback when relevant."""),
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

    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "author": state.author,
        "context_summary": state.context_summary,
        "code_analysis": state.code_analysis,
        "critique": state.critique
    })

    state.final_comment = response.content
    state.traces.append({
        "agent": "FinalRecommender",
        "output": response.content
    })
    return state

def context_summarizer(state: ReviewState) -> ReviewState:
    """Summarizes the raw context retrieved from knowledge base"""
    llm = get_llm(temperature=0.2, max_tokens=600)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a helpful assistant that summarizes technical context from a codebase.
Your job is to create a concise summary of the provided code/documentation chunks that are relevant to the current Pull Request.
Focus on:
- Key functions, classes, or modules mentioned
- Important logic or architecture details
- Any patterns that the PR seems to be modifying or extending

Keep the summary short and focused."""),
        ("human", """PR Title: {title}

Raw context from knowledge base:
{raw_context}

Please provide a concise summary of the relevant codebase context.""")
    ])

    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "raw_context": state.summarized_context
    })

    state.summarized_context = response.content
    state.traces.append({
        "agent": "ContextSummarizer",
        "output": response.content
    })
    return state