from langchain_core.prompts import ChatPromptTemplate
from typing import List

from core.state import ReviewState
from core.models import Finding, ReviewOutput, Findings
from core.evidence import EvidencePackage
from core.hybrid_retriever import HybridRetriever
from core.context_builder import ContextBuilder
from core.gateway import gateway
from core.query_builder import QueryBuilder
from core.knowledge_base import KnowledgeBase


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
        raw_context=state.get("context_from_kb") or "",
    )

    response = gateway.generate(
        prompt=prompt,
        capability="summarization",
        temperature=0.2,
        max_tokens=600,
        agent_name="ContextSummarizer",
    )

    return {
        "summarized_context": response.content,
        "traces": [{"agent": "ContextSummarizer", "output": response.content}],
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
        context_to_use=state.get("summarized_context") or "",
    )

    response = gateway.generate(
        prompt=prompt,
        capability="context_gathering",
        temperature=0.3,
        max_tokens=800,
        agent_name="ContextGatherer",
    )

    return {
        "context_summary": response.content,
        "traces": [{"agent": "ContextGatherer", "output": response.content}],
    }


def correctness_agent(state: ReviewState) -> dict:
    evidence_package = state.get("evidence_package")
    pr_understanding = state.get("pr_understanding", {})
    pr_analysis = state.get("pr_analysis", {})

    evidence_summary = ""
    if evidence_package is not None and hasattr(evidence_package, "summary"):
        evidence_summary = evidence_package.summary or ""

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Correctness Reviewer.

Your ONLY job is to find functional correctness issues, logic errors, edge cases, and potential bugs.

Rules:
- Every finding MUST be supported by retrieved evidence.
- If evidence is insufficient, return an empty findings list.
- Be highly critical and specific.
- Cite evidence IDs or file paths from the evidence block.
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
        evidence_summary=evidence_summary,
        rich_context=(state.get("context_from_kb") or "")[:10000],
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="correctness_review",
        agent_name="CorrectnessAgent",
    )

    findings = result.findings if hasattr(result, "findings") else []

    return {
        "correctness_findings": findings,
        "traces": [{
            "agent": "CorrectnessAgent",
            "output": f"Found {len(findings)} correctness findings",
        }],
    }


def code_quality_agent(state: ReviewState) -> dict:
    evidence_package = state.get("evidence_package")
    pr_understanding = state.get("pr_understanding", {})
    pr_analysis = state.get("pr_analysis", {})

    evidence_summary = ""
    if evidence_package is not None and hasattr(evidence_package, "summary"):
        evidence_summary = evidence_package.summary or ""

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Code Quality Reviewer.

Your ONLY job is to evaluate code style, maintainability, readability, best practices, and technical debt.

Rules:
- Every finding MUST be supported by retrieved evidence.
- If evidence is insufficient, return an empty findings list.
- Be constructive but critical.
- Cite evidence IDs or file paths from the evidence block.
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
        evidence_summary=evidence_summary,
        rich_context=(state.get("context_from_kb") or "")[:10000],
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="code_quality_review",
        agent_name="CodeQualityAgent",
    )

    findings = result.findings if hasattr(result, "findings") else []

    return {
        "quality_findings": findings,
        "traces": [{
            "agent": "CodeQualityAgent",
            "output": f"Found {len(findings)} code quality findings",
        }],
    }


def build_evidence_package(state: ReviewState) -> dict:
    """
    After PR Analysis: hybrid retrieval → EvidencePackage.
    Fails loud if the knowledge base returns nothing.
    """
    repo = state.get("repo") or ""
    collection = repo.replace("/", "_")

    kb = state.get("kb")
    if kb is None:
        kb = KnowledgeBase(collection)

    files_changed = [
        p.replace("\\", "/")
        for p in (state.get("files_changed") or [])
    ]

    query = f"{state.get('title', '')}\n{state.get('body') or ''}"

    graph_queries = None
    try:
        from core.repository_intelligence.graph.queries import GraphQueries
        graph_queries = GraphQueries()
    except Exception as e:
        print(f"[build_evidence_package] GraphQueries unavailable: {e}")

    retriever = HybridRetriever(
        repo,
        kb=kb,
        graph_queries=graph_queries,
        require_kb=True,
    )

    # Returns EvidencePackage; raises RuntimeError if empty
    package = retriever.retrieve(
        query=query,
        pr_understanding=state.get("pr_understanding") or {},
        files_changed=files_changed,
        k=8,
        use_calls=True,
        fail_if_empty=True,
    )

    # Prefer ContextBuilder string if available; else synthesize from evidences
    rich_context = ""
    if hasattr(ContextBuilder, "to_agent_context"):
        try:
            rich_context = ContextBuilder.to_agent_context(package) or ""
        except Exception:
            rich_context = ""

    if not rich_context:
        parts = []
        evidences = getattr(package, "evidences", None) or []
        for i, ev in enumerate(evidences):
            path = getattr(ev, "path", None) or (getattr(ev, "metadata", {}) or {}).get("path", "?")
            content = getattr(ev, "page_content", None) or getattr(ev, "content", None) or str(ev)
            parts.append(f"### [{i}] {path}\n{content}")
        if not parts and getattr(package, "summary", None):
            parts.append(package.summary)
        rich_context = "\n\n".join(parts)

    n = len(getattr(package, "evidences", None) or [])
    print(f"[build_evidence_package] EvidencePackage with {n} items")

    return {
        "evidence_package": package,
        "context_from_kb": rich_context,
        "traces": [{
            "agent": "BuildEvidencePackage",
            "output": f"Built EvidencePackage with {n} items",
        }],
    }


def critic_agent(state: ReviewState) -> dict:
    """Aggregate findings (LLM critic can replace this later)."""
    correctness = state.get("correctness_findings") or []
    quality = state.get("quality_findings") or []
    all_findings = list(correctness) + list(quality)

    return {
        "findings": all_findings,
        "traces": [{
            "agent": "CriticAgent",
            "output": f"Aggregated {len(all_findings)} findings from specialized agents",
        }],
    }


def final_recommender(state: ReviewState) -> dict:
    findings = state.get("findings") or []
    finding_lines = []
    for f in findings:
        if hasattr(f, "title"):
            finding_lines.append(
                f"{f.title} ({getattr(f, 'severity', '?')}): {getattr(f, 'description', '')}"
            )
        else:
            finding_lines.append(str(f))

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior maintainer giving the final review decision.

Synthesize the provided findings into a clear, actionable recommendation.

Be balanced, specific, and professional.
Recommendation must be one of: MERGE, REQUEST_CHANGES, COMMENT."""),
        ("human", """PR Context:
{context_summary}

Findings:
{findings}

Provide the final recommendation and a ready-to-post comment.""")
    ]).format(
        context_summary=state.get("context_summary") or "",
        findings="\n".join(finding_lines) if finding_lines else "No findings.",
    )

    response = gateway.generate_structured(
        prompt=prompt,
        schema=ReviewOutput,
        capability="final_recommendation",
        agent_name="FinalRecommender",
    )

    return {
        "final_comment": getattr(response, "summary", None) or str(response),
        "recommendation": getattr(response, "recommendation", None) or "COMMENT",
        "traces": [{
            "agent": "FinalRecommender",
            "output": str(response),
        }],
    }