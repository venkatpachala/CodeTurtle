from langchain_core.prompts import ChatPromptTemplate
from core.llm import get_llm
from core.state import ReviewState, ReviewOutput


def context_summarizer(state: ReviewState) -> dict:
    llm = get_llm(temperature=0.2, max_tokens=600)
    response = (ChatPromptTemplate.from_messages([
        ("system", "You are an expert repository context summarizer."),
        ("human", "PR Title: {title}\nRaw context from repository: {raw_context}")
    ]) | llm).invoke({
        "title": state["title"],
        "raw_context": state["context_from_kb"]
    })
    return {
        "summarized_context": response.content,
        "traces": [{"agent": "ContextSummarizer", "output": response.content}]
    }


def context_gatherer(state: ReviewState) -> dict:
    llm = get_llm(temperature=0.3, max_tokens=800)
    response = (ChatPromptTemplate.from_messages([
        ("system", "You are an expert Context Gatherer for GitHub code reviews."),
        ("human", "PR Title: {title}\nPR Body: {body}\nSummarized repository context: {context_to_use}")
    ]) | llm).invoke({
        "title": state["title"],
        "body": state["body"],
        "context_to_use": state["summarized_context"]
    })
    return {
        "context_summary": response.content,
        "traces": [{"agent": "ContextGatherer", "output": response.content}]
    }


def code_quality_reviewer(state: ReviewState) -> dict:
    llm = get_llm(temperature=0.2, max_tokens=1200)
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior Code Quality Reviewer with access to the full repository context.
Focus on code quality, maintainability, architecture, and best practices.
Be specific and critical."""),
        ("human", """PR Title: {title}
PR Body: {body}

Relevant repository context:
{context_to_use}

Code changes:
{diff}

Provide detailed code quality analysis.""")
    ])
    structured_llm = llm.with_structured_output(ReviewOutput)
    chain = prompt | structured_llm
    response = chain.invoke({
        "title": state["title"],
        "body": state["body"],
        "context_to_use": state["summarized_context"],
        "diff": state["full_diff"]
    })
    return {
        "code_analysis": response,
        "traces": [{"agent": "CodeQualityReviewer", "output": str(response)}]
    }


def critic_agent(state: ReviewState) -> dict:
    llm = get_llm(temperature=0.2, max_tokens=1000)
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Code Review Critic.
Critique the previous analysis.
Find missing points, overconfidence, or overlooked issues."""),
        ("human", """PR Title: {title}

Context Summary:
{context_summary}

Code Analysis:
{code_analysis}

Provide critical feedback.""")
    ])
    structured_llm = llm.with_structured_output(ReviewOutput)
    chain = prompt | structured_llm
    response = chain.invoke({
        "title": state["title"],
        "context_summary": state["context_summary"],
        "code_analysis": state["code_analysis"]
    })
    return {
        "critique": response,
        "traces": [{"agent": "Critic", "output": str(response)}]
    }


def final_recommender(state: ReviewState) -> dict:
    llm = get_llm(temperature=0.3, max_tokens=1500)
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior maintainer giving the final review decision.
Based on all previous analysis, give a clear recommendation and professional comment."""),
        ("human", """PR Title: {title}

Context Summary:
{context_summary}

Code Analysis:
{code_analysis}

Critique:
{critique}

Give your final recommendation.""")
    ])
    structured_llm = llm.with_structured_output(ReviewOutput)
    chain = prompt | structured_llm
    response = chain.invoke({
        "title": state["title"],
        "context_summary": state["context_summary"],
        "code_analysis": state["code_analysis"],
        "critique": state["critique"]
    })
    return {
        "final_comment": str(response),
        "recommendation": response.get("recommendation", "COMMENT"),
        "traces": [{"agent": "FinalRecommender", "output": str(response)}]
    }