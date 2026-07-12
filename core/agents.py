from langchain_core.prompts import ChatPromptTemplate
from core.llm import get_llm
from core.state import ReviewState

def context_gatherer(state: ReviewState) -> ReviewState:
    """Agent that gathers context and flags what to investigate"""
    llm = get_llm(temperature=0.3)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert Context Gatherer for GitHub code reviews.
Your job is to analyze the PR and extract key context:
- What is the PR trying to achieve?
- Any red flags in the description or linked issues?
- What should the Code Reviewer focus on?
Be concise but insightful."""),
        ("human", """PR Title: {title}
PR Body: {body}
Author: {author}

Relevant code from repository knowledge base:
{context_from_kb}

Please provide a clear summary of context and what the next agent should investigate.""")
    ])
    
    chain = prompt | llm
    response = chain.invoke({
    "title": state.title,
    "body": state.body,
    "author": state.author,
    "context_from_kb": state.context_from_kb
})
    
    state.context_summary = response.content
    state.traces.append({
        "agent": "ContextGatherer",
        "output": response.content,
        "timestamp": str(state.created_at)
    })
    return state


def code_quality_reviewer(state: ReviewState) -> ReviewState:
    """Agent that reviews the code diff for quality issues"""
    llm = get_llm(temperature=0.2)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior Code Quality Reviewer.
Focus on:
- Code correctness and bugs
- Readability and maintainability
- Best practices for the language
- Security concerns
- Test coverage (if tests are present)
Be constructive and specific. Reference line numbers or functions when possible."""),
        ("human", """PR Title: {title}
Context from previous agent: {context_summary}

Code Diff:
{diff}

Please provide a detailed code quality analysis.""")
    ])
    
    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "context_summary": state.context_summary,
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
    llm = get_llm(temperature=0.2)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Code Review Critic.
Your job is to review the outputs of the previous agents and improve them.
Check for:
- Missing important issues
- Incorrect or weak analysis
- Lack of specificity
- Poor reasoning

Be direct and constructive."""),
        ("human", """PR Title: {title}

Context Summary:
{context_summary}

Code Quality Analysis:
{code_analysis}

Please critique the above analysis and suggest improvements.""")
    ])

    chain = prompt | llm
    response = chain.invoke({
        "title": state.title,
        "context_summary": state.context_summary,
        "code_analysis": state.code_analysis
    })

    state.critique = response.content
    state.traces.append({
        "agent": "Critic",
        "output": response.content
    })
    return state


def final_recommender(state: ReviewState) -> ReviewState:
    """Final agent that gives recommendation and generates comment"""
    llm = get_llm(temperature=0.3)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior maintainer giving the final review decision.
Based on all previous analysis, give:
1. A clear recommendation: MERGE, REQUEST_CHANGES, or COMMENT
2. A professional, constructive comment that can be posted on GitHub.

Be balanced and specific."""),
        ("human", """PR Title: {title}
Author: {author}

Context Summary:
{context_summary}

Code Analysis:
{code_analysis}

Critique:
{critique}

Please give your final recommendation and a ready-to-post comment.""")
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