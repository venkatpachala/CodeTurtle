from langchain_core.prompts import ChatPromptTemplate

from core.state import ReviewState
from core.models import PRAnalysis
from core.gateway import gateway


def pr_analysis_agent(state: ReviewState) -> dict:
    """Deterministic + LLM PR Analysis."""

    # TODO: Add deterministic part later (GitHub API + AST)
    # For now, LLM-based

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert senior software engineer performing deterministic PR analysis.

Extract factual information from the PR. Be precise and technical."""),

        ("human", """PR Title: {title}

PR Body: {body}

Files Changed: {files_changed}

Full Diff (truncated): {diff}

Extract the following facts:""")
    ]).format(
        title=state.get("title", ""),
        body=state.get("body", ""),
        files_changed="\n".join(state.get("files_changed", [])),
        diff=(state.get("full_diff") or "")[:8000]
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=PRAnalysis,
        capability="reasoning",
        agent_name="PRAnalysisAgent"
    )

    return {
        "pr_analysis": result.model_dump(),
        "traces": [{
            "agent": "PRAnalysisAgent",
            "output": result.model_dump_json(indent=2)
        }]
    }