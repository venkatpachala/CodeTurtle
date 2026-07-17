from langchain_core.prompts import ChatPromptTemplate
from core.llm import get_llm
from core.state import ReviewState, PRUnderstanding


def pr_understanding_agent(state: ReviewState) -> dict:
    """
    First agent in the review pipeline.
    Analyzes the PR title, body, and changed files to produce a structured understanding.
    """

    llm = get_llm(temperature=0.2, max_tokens=1200)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert senior software engineer performing the first-pass analysis of a GitHub Pull Request.

Your job is **not** to review the code in depth yet. Your job is to deeply understand the *nature* of the change.

You must produce a structured analysis that will guide the rest of the review process.

Be precise, technical, and concise."""),

        ("human", """Analyze this Pull Request carefully.

### PR Title
{title}

### PR Description
{body}

### Files Changed
{files_changed}

### Full Diff (truncated if very long)
{diff}

---

Based on the above, produce a structured understanding of this PR.

Focus on:
1. What is the main purpose of this change?
2. What categories does this change fall into? (feature, bugfix, refactor, docs, test, config, dependency, api, ui, performance, security, chore)
3. How risky is this change? (low / medium / high / critical)
4. Which high-level areas of the system are affected?
5. What should later specialized reviewers focus on?
6. Are there any obvious potential risks?
7. Were tests and documentation updated?

Respond with a structured JSON that matches the PRUnderstanding schema.""")
    ])

    structured_llm = llm.with_structured_output(PRUnderstanding)

    chain = prompt | structured_llm

    result = chain.invoke({
        "title": state.get("title", ""),
        "body": state.get("body", "") or "No description provided.",
        "files_changed": "\n".join(state.get("files_changed", [])),
        "diff": (state.get("full_diff") or "")[:12000]  # Truncate very large diffs
    })

    return {
        "pr_understanding": result.model_dump(),
        "traces": [{
            "agent": "PRUnderstanding",
            "output": result.model_dump_json(indent=2)
        }]
    }