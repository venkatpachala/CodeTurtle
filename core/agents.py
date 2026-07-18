from langchain_core.prompts import ChatPromptTemplate
from typing import List

from core.state import ReviewState
from core.models import Finding, ReviewOutput, Findings
from core.evidence import EvidencePackage
from core.hybrid_retriever import HybridRetriever
from core.context_builder import ContextBuilder
from core.gateway import gateway


def context_summarizer(state: ReviewState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert repository analyst.

Your job is to create a concise, high-signal summary of the repository context relevant to this PR.

Focus on:
- Key files and modules touched
- Relevant symbols, classes, functions
- Architecture patterns
- Dependencies

Be technical and precise. Do not speculate."""),
        ("human", """PR Title: {title}

Retrieved Repository Context:
{raw_context}

Summarize only the most relevant parts for code review.""")
    ]).format(
        title=state["title"],
        raw_context=state["context_from_kb"]
    )

    response = gateway.generate(
        prompt=prompt,
        capability="summarization",
        temperature=0.2,
        max_tokens=600,
        agent_name="ContextSummarizer"
    )

    return {
        "summarized_context": response.content,
        "traces": [{"agent": "ContextSummarizer", "output": response.content}]
    }


def context_gatherer(state: ReviewState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert PR context gatherer.

Your job is to create a focused summary of the PR and relevant repository context for downstream reviewers.

Highlight:
- Main intent of the PR
- Key changes
- Potential impact areas
- What reviewers should focus on"""),
        ("human", """PR Title: {title}

PR Body: {body}

Summarized Repository Context:
{context_to_use}

Provide a concise, actionable summary for code reviewers.""")
    ]).format(
        title=state["title"],
        body=state.get("body", ""),
        context_to_use=state["summarized_context"]
    )

    response = gateway.generate(
        prompt=prompt,
        capability="context_gathering",
        temperature=0.3,
        max_tokens=800,
        agent_name="ContextGatherer"
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

Your ONLY job is to find functional correctness issues, logic errors, edge cases, and potential bugs.

Rules:
- Every finding MUST be supported by retrieved evidence.
- If evidence is insufficient, return empty list.
- Be highly critical and specific.
- Cite evidence IDs or file paths.
- Never speculate or invent code that was not retrieved."""),
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
        capability="correctness_review",
        agent_name="CorrectnessAgent"
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

Your ONLY job is to evaluate code style, maintainability, readability, best practices, and technical debt.

Rules:
- Every finding MUST be supported by retrieved evidence.
- If evidence is insufficient, return empty list.
- Be constructive but critical.
- Cite evidence IDs or file paths.
- Never speculate or invent code that was not retrieved."""),
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
        capability="code_quality_review",
        agent_name="CodeQualityAgent"
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
        ("system", """You are a senior maintainer giving the final review decision.

Synthesize the provided findings into a clear, actionable recommendation.

Be balanced, specific, and professional."""),
        ("human", """PR Context:
{context_summary}

Findings:
{findings}

Provide the final recommendation and a ready-to-post comment.""")
    ]).format(
        context_summary=state.get("context_summary", ""),
        findings="\n".join([f"{f.title} ({f.severity}): {f.description}" for f in state.get("findings", [])])
    )

    response = gateway.generate_structured(
        prompt=prompt,
        schema=ReviewOutput,
        capability="final_recommendation",
        agent_name="FinalRecommender"
    )

    return {
        "final_comment": response.summary or "",
        "recommendation": response.recommendation or "COMMENT",
        "traces": [{
            "agent": "FinalRecommender",
            "output": str(response)
        }]
    }