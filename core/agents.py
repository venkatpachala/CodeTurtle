from langchain_core.prompts import ChatPromptTemplate
from typing import List

from core.state import ReviewState
from core.models import Finding, ReviewOutput, Findings
from core.evidence import EvidencePackage
from core.hybrid_retriever import HybridRetriever
from core.context_builder import ContextBuilder
from core.gateway.gateway import AIGateway

# Global gateway instance
gateway = AIGateway()


def context_summarizer(state: ReviewState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Summarize relevant repository context."),
        ("human", "PR Title: {title}\nRaw context: {raw_context}")
    ]).format(
        title=state["title"],
        raw_context=state["context_from_kb"]
    )

    response = gateway.generate(
        prompt=prompt,
        capability="summarization",
        temperature=0.2,
        max_tokens=600
    )

    return {
        "summarized_context": response.content,
        "traces": [{"agent": "ContextSummarizer", "output": response.content}]
    }


def context_gatherer(state: ReviewState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Gather PR context."),
        ("human", "PR Title: {title}\nContext: {context_to_use}")
    ]).format(
        title=state["title"],
        context_to_use=state["summarized_context"]
    )

    response = gateway.generate(
        prompt=prompt,
        capability="context_gathering",
        temperature=0.3,
        max_tokens=800
    )

    return {
        "context_summary": response.content,
        "traces": [{"agent": "ContextGatherer", "output": response.content}]
    }


def correctness_agent(state: ReviewState) -> dict:
    """
    Specialized Correctness Agent using Gateway.
    """
    evidence_package = state.get("evidence_package")
    pr_understanding = state.get("pr_understanding", {})
    pr_analysis = state.get("pr_analysis", {})

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Correctness Reviewer.

Your only job is to find functional correctness issues, logic errors, edge cases, and potential bugs.

You must produce structured findings only. Be critical and precise."""),
        ("human", """PR Understanding:
{pr_understanding}

PR Analysis:
{pr_analysis}

Retrieved Evidence:
{evidence_summary}

Full context from relevant files:
{rich_context}

Find correctness issues in this PR.""")
    ]).format(
        pr_understanding=pr_understanding,
        pr_analysis=pr_analysis,
        evidence_summary=evidence_package.summary if evidence_package else "",
        rich_context=state.get("context_from_kb", "")[:10000]
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="correctness_review"
    )

    findings = result.findings

    return {
        "correctness_findings": findings,
        "traces": [{"agent": "CorrectnessAgent", "output": f"Found {len(findings)} correctness findings"}]
    }


def code_quality_agent(state: ReviewState) -> dict:
    """
    Specialized Code Quality Agent using Gateway.
    """
    evidence_package = state.get("evidence_package")
    pr_understanding = state.get("pr_understanding", {})
    pr_analysis = state.get("pr_analysis", {})

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Code Quality Reviewer.

Your only job is to evaluate code style, maintainability, readability, best practices, and technical debt.

You must produce structured findings only. Be constructive but critical."""),
        ("human", """PR Understanding:
{pr_understanding}

PR Analysis:
{pr_analysis}

Retrieved Evidence:
{evidence_summary}

Full context from relevant files:
{rich_context}

Find code quality issues in this PR.""")
    ]).format(
        pr_understanding=pr_understanding,
        pr_analysis=pr_analysis,
        evidence_summary=evidence_package.summary if evidence_package else "",
        rich_context=state.get("context_from_kb", "")[:10000]
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="code_quality_review"
    )

    findings = result.findings

    return {
        "quality_findings": findings,
        "traces": [{"agent": "CodeQualityAgent", "output": f"Found {len(findings)} code quality findings"}]
    }


def build_evidence_package(state: ReviewState) -> dict:
    """Runs inside the graph after PR Analysis."""
    query = f"{state['title']}\n{state['body']}"

    retriever = HybridRetriever(state["repo"], kb=state.get("kb"))
    evidence_package = retriever.retrieve(
        query=query,
        pr_understanding=state.get("pr_understanding", {}),
        k=8
    )

    rich_context = ContextBuilder.to_agent_context(evidence_package)

    return {
        "evidence_package": evidence_package,
        "context_from_kb": rich_context,
        "traces": [{
            "agent": "BuildEvidencePackage",
            "output": f"Built EvidencePackage with {len(evidence_package.evidences)} items"
        }]
    }


def critic_agent(state: ReviewState) -> dict:
    correctness = state.get("correctness_findings", [])
    quality = state.get("quality_findings", [])

    all_findings = correctness + quality

    return {
        "findings": all_findings,
        "traces": [{
            "agent": "CriticAgent",
            "output": f"Aggregated {len(all_findings)} findings from specialized agents"
        }]
    }


def final_recommender(state: ReviewState) -> dict:
    """
    Final Recommender that produces the final recommendation and comment.
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a senior maintainer giving the final review decision."),
        ("human", "Context: {context_summary}\nFindings: {findings}")
    ]).format(
        context_summary=state.get("context_summary", ""),
        findings="\n".join([f"{f.title} ({f.severity}): {f.description}" for f in state.get("findings", [])])
    )

    response = gateway.generate_structured(
        prompt=prompt,
        schema=ReviewOutput,
        capability="final_recommendation"
    )

    return {
        "final_comment": response.summary or "",
        "recommendation": response.recommendation or "COMMENT",
        "traces": [{
            "agent": "FinalRecommender",
            "output": str(response)
        }]
    }