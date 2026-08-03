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
from core.query_engine import RepositoryQueryEngine
from core.state import ReviewState



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

You are a senior engineer doing a correctness review of a GitHub PR.

You may ONLY use:
- The PR title/body/diff summary provided
- The retrieved evidence blocks (path + code)

Rules:
1. Every finding MUST include evidence that points to a path (and line range if possible).
2. Do NOT invent APIs, files, or behaviors not present in the evidence or diff.
3. Prefer real bugs: logic errors, edge cases, broken invariants, missing error handling, regressions.
4. If evidence is thin, emit fewer findings with lower confidence — never pad with generic advice.
5. Skip pure style/naming unless it causes a real defect."""),
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
Mandatory output rules:
- Each finding must name at least one file path that appears in the evidence/context.
- Each finding must quote or paraphrase a concrete code behavior from the evidence or diff.
- If you cannot do both, return zero findings.
- Do not comment on files that were not retrieved.
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

def build_evidence_package(state: dict) -> dict:
    from core.query_engine import RepositoryQueryEngine
    from core.review_intelligence.models import ReviewPlan, RetrievalQuestion

    repo = state["repo"]
    engine = state.get("engine")
    if engine is None:
        engine = RepositoryQueryEngine(repo, kb=state.get("kb"))

    plan_raw = state.get("review_plan") or {}
    try:
        plan = ReviewPlan.model_validate(plan_raw) if plan_raw else None
    except Exception:
        plan = None

    files_changed = list(state.get("files_changed") or [])
    understanding = state.get("pr_understanding") or {}

    packages = []
    if plan and plan.retrieval_questions:
        for q in plan.retrieval_questions[:10]:
            if isinstance(q, dict):
                q = RetrievalQuestion.model_validate(q)
            pkg = engine.retrieve_context(
                query=q.question,
                files_changed=q.prefer_paths or files_changed,
                symbols=q.prefer_symbols or [],
                k=6,
                pr_understanding=understanding if isinstance(understanding, dict) else {},
            )
            packages.append(pkg)
    else:
        query = f"{state.get('title', '')}\n{state.get('body', '')}"
        packages.append(
            engine.retrieve_context(
                query=query,
                files_changed=files_changed,
                k=8,
                pr_understanding=understanding if isinstance(understanding, dict) else {},
            )
        )

    # Merge / dedupe evidences
    evidence_package = _merge_packages(packages, max_items=16)
    rich_context = _format_evidence(evidence_package)  # your ContextBuilder if present

    return {
        "evidence_package": evidence_package,
        "context_from_kb": rich_context,
        "traces": [
            {
                "agent": "BuildEvidencePackage",
                "output": f"plan_questions={len(plan.retrieval_questions) if plan else 0} merged={getattr(evidence_package, 'count', len(getattr(evidence_package, 'evidences', []) or []))}",
            }
        ],
    }


def _merge_packages(packages, max_items: int = 16):
    """Dedupe by path+content prefix; keep first EvidencePackage type if possible."""
    if not packages:
        return packages
    seen = set()
    merged = []
    for pkg in packages:
        evs = getattr(pkg, "evidences", None) or []
        for ev in evs:
            path = getattr(ev, "path", "") or ""
            content = (getattr(ev, "content", None) or getattr(ev, "page_content", "") or "")[:80]
            key = (path, content)
            if key in seen:
                continue
            seen.add(key)
            merged.append(ev)
            if len(merged) >= max_items:
                break
        if len(merged) >= max_items:
            break

    head = packages[0]
    # Prefer mutating a copy-like structure
    try:
        from dataclasses import replace
        if hasattr(head, "evidences"):
            return replace(head, evidences=merged) if hasattr(head, "__dataclass_fields__") else head
    except Exception:
        pass
    # Fallback: set attribute
    try:
        head.evidences = merged
        if hasattr(head, "count"):
            head.count = len(merged)
    except Exception:
        pass
    return head


def _format_evidence(evidence_package) -> str:
    try:
        from core.context_builder import ContextBuilder
        return ContextBuilder.to_agent_context(evidence_package)
    except Exception:
        lines = []
        for i, ev in enumerate(getattr(evidence_package, "evidences", None) or [], 1):
            path = getattr(ev, "path", "")
            content = (getattr(ev, "content", None) or getattr(ev, "page_content", "") or "")[:1500]
            lines.append(f"[{i}] path={path}\n{content}\n")
        return "\n".join(lines) if lines else "(no evidence)"


def _evidence_to_agent_context(package) -> str:
    """Flatten EvidencePackage into a string agents already expect."""
    # Prefer existing ContextBuilder if present
    try:
        from core.context_builder import ContextBuilder
        if hasattr(ContextBuilder, "to_agent_context"):
            return ContextBuilder.to_agent_context(package)
    except Exception:
        pass

    parts = []
    evidences = getattr(package, "evidences", None) or []
    for i, ev in enumerate(evidences):
        path = getattr(ev, "path", "") or ""
        source = getattr(ev, "source", "") or ""
        content = getattr(ev, "content", "") or ""
        parts.append(f"### Evidence {i + 1} | {path} | source={source}\n{content}")
    return "\n\n".join(parts) if parts else "No repository evidence retrieved."


def critic_agent(state: ReviewState) -> dict:
    """
    Filter specialized findings: keep only evidence-backed, non-duplicate items.
    """
    correctness = state.get("correctness_findings") or []
    quality = state.get("quality_findings") or []

    def _fmt(findings) -> str:
        lines = []
        for i, f in enumerate(findings):
            if hasattr(f, "model_dump"):
                lines.append(f"[{i}] {f.model_dump()}")
            elif hasattr(f, "title"):
                lines.append(
                    f"[{i}] {f.title} | {getattr(f, 'severity', '')} | "
                    f"{getattr(f, 'description', '')} | evidence={getattr(f, 'evidence', getattr(f, 'evidence_ids', ''))}"
                )
            else:
                lines.append(f"[{i}] {f}")
        return "\n".join(lines) if lines else "(none)"

    evidence_summary = ""
    ep = state.get("evidence_package")
    if ep is not None and hasattr(ep, "summary"):
        evidence_summary = ep.summary or ""

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior staff engineer acting as Critic for an automated PR review.

You are a strict review critic. Input: findings from Correctness and Code Quality.

For each finding decide: KEEP | DROP | MERGE.

DROP when:
- No valid evidence path / contradiction with evidence
- Duplicate of another finding
- Generic advice with no PR-specific basis
- Conflicts with deterministic PR analysis without justification

Output:
- kept_findings (deduplicated, tightened titles)
- dropped_summary (short reasons)
- overall_assessment"""),
        ("human", """PR title: {title}

Evidence summary:
{evidence_summary}

Context (truncated):
{context}

Correctness findings:
{correctness}

Code quality findings:
{quality}

Produce the final filtered findings list.""")
    ]).format(
        title=state.get("title", ""),
        evidence_summary=evidence_summary,
        context=(state.get("context_from_kb") or "")[:8000],
        correctness=_fmt(correctness),
        quality=_fmt(quality),
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="reasoning",
        agent_name="CriticAgent",
    )

    findings = result.findings if hasattr(result, "findings") else []

    return {
        "findings": findings,
        "traces": [{
            "agent": "CriticAgent",
            "output": (
                f"Filtered {len(correctness) + len(quality)} → {len(findings)} findings"
            ),
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
Recommendation must be one of: MERGE, REQUEST_CHANGES, COMMENT.
If any high/critical kept finding → REQUEST_CHANGES
Else if medium findings → COMMENT or REQUEST_CHANGES based on confidence
Else if only low / none → MERGE (with residual risk note)"""),
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