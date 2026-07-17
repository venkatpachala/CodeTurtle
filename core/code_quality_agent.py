from langchain_core.prompts import ChatPromptTemplate
from typing import List

from core.llm import get_llm
from core.state import ReviewState
from core.models import Finding, Findings
from core.evidence import EvidencePackage


def code_quality_agent(state: ReviewState) -> dict:
    """
    Specialized Code Quality Agent.
    """

    llm = get_llm(temperature=0.2, max_tokens=1500)

    evidence_package = state.get("evidence_package", {})
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
    ])

    structured_llm = llm.with_structured_output(Findings)

    chain = prompt | structured_llm

    result = chain.invoke({
        "pr_understanding": pr_understanding,
        "pr_analysis": pr_analysis,
        "evidence_summary": evidence_package.get("summary", ""),
        "rich_context": state.get("context_from_kb", "")[:10000]
    })

    findings = result.findings

    return {
        "quality_findings": findings,
        "traces": [{
            "agent": "CodeQualityAgent",
            "output": f"Found {len(findings)} code quality findings"
        }]
    }