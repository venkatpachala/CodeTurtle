from langchain_core.prompts import ChatPromptTemplate
from core.llm import get_llm
from core.state import ReviewState
from core.models import Finding
from core.evidence import EvidencePackage
from typing import List


def correctness_agent(state: ReviewState) -> dict:
    """
    Specialized Correctness Agent.

    Focuses on functional correctness, logic errors, edge cases, and potential bugs.
    """

    llm = get_llm(temperature=0.2, max_tokens=1500)

    evidence_package = state.get("evidence_package", {})
    pr_understanding = state.get("pr_understanding", {})
    pr_analysis = state.get("pr_analysis", {})

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict and experienced Correctness Reviewer.

Your only job is to find functional correctness issues, logic errors, edge cases, and potential bugs.

You must produce structured findings only. Be critical and precise.

Every finding must include:
- Clear title
- Detailed description
- Evidence (specific code)
- Reasoning
- Recommendation
- Severity and confidence"""),

        ("human", """PR Understanding:
{pr_understanding}

PR Analysis:
{pr_analysis}

Retrieved Evidence:
{evidence_summary}

Full context from relevant files:
{rich_context}

Find correctness issues in this PR.""")
    ])

    structured_llm = llm.with_structured_output(List[Finding])

    chain = prompt | structured_llm

    findings = chain.invoke({
        "pr_understanding": pr_understanding,
        "pr_analysis": pr_analysis,
        "evidence_summary": evidence_package.get("summary", ""),
        "rich_context": state.get("context_from_kb", "")[:10000]
    })

    return {
        "findings": findings,
        "traces": [{
            "agent": "CorrectnessAgent",
            "output": f"Found {len(findings)} correctness findings"
        }]
    }