from langchain_core.prompts import ChatPromptTemplate
from core.llm import get_llm
from core.state import ReviewState, ReviewOutput


def context_summarizer(state: ReviewState) -> dict:
    llm = get_llm(temperature=0.2, max_tokens=600)
    response = (ChatPromptTemplate.from_messages([
        ("system", "Summarize relevant repository context."),
        ("human", "PR Title: {title}\nRaw context: {raw_context}")
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
        ("system", "Gather PR context."),
        ("human", "PR Title: {title}\nContext: {context_to_use}")
    ]) | llm).invoke({
        "title": state["title"],
        "context_to_use": state["summarized_context"]
    })
    return {
        "context_summary": response.content,
        "traces": [{"agent": "ContextGatherer", "output": response.content}]
    }


def code_quality_reviewer(state: ReviewState) -> dict:
    llm = get_llm(temperature=0.2, max_tokens=1200)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a senior Code Quality Reviewer."),
        ("human", "PR Title: {title}\nDiff: {diff}\nContext: {context_to_use}")
    ])
    structured_llm = llm.with_structured_output(ReviewOutput)
    chain = prompt | structured_llm
    response = chain.invoke({
        "title": state["title"],
        "diff": state["full_diff"],
        "context_to_use": state["summarized_context"]
    })
    return {
        "code_analysis": response,
        "traces": [{"agent": "CodeQualityReviewer", "output": str(response)}]
    }


def critic_agent(state: ReviewState) -> dict:
    llm = get_llm(temperature=0.2, max_tokens=1000)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a strict and experienced Code Review Critic."),
        ("human", "Context: {context_summary}\nAnalysis: {code_analysis}")
    ])
    structured_llm = llm.with_structured_output(ReviewOutput)
    chain = prompt | structured_llm
    response = chain.invoke({
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
        ("system", "You are a senior maintainer giving the final review decision."),
        ("human", "Context: {context_summary}\nAnalysis: {code_analysis}\nCritique: {critique}")
    ])
    structured_llm = llm.with_structured_output(ReviewOutput)
    chain = prompt | structured_llm
    response = chain.invoke({
        "context_summary": state["context_summary"],
        "code_analysis": state["code_analysis"],
        "critique": state["critique"]
    })
    return {
        "final_comment": str(response),
        "recommendation": response.get("recommendation", "COMMENT"),
        "traces": [{"agent": "FinalRecommender", "output": str(response)}]
    }