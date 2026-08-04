from langchain_core.prompts import ChatPromptTemplate

from core.state import ReviewState
from core.models import PRUnderstanding
from core.gateway import gateway


CORE_PATH_HINTS = (
    "core",
    "engine",
    "main",
    "runtime",
    "auth",
    "db",
    "api",
    "server",
    "client",
    "model",
    "service",
    "security",
    "migrate",
    "cache",
)

BANNED_RISK_PHRASES = (
    "subtle",
    "thoroughly",
    "edge cases",
    "interact poorly",
    "as stated by the author",
    "may introduce",
    "carefully reviewed",
)


def refine_understanding(
    result: PRUnderstanding,
    files: list[str],
    body: str,
) -> PRUnderstanding:
    """
    Deterministic post-process after structured LLM output.
    Nudges risk, fills out-of-scope notes, drops generic risk fluff.
    """
    files_l = " ".join(files or []).lower()

    change_types = [str(c).lower() for c in (result.change_type or [])]
    is_bugfix = any(t in change_types for t in ("bug", "bugfix", "fix"))

    # Core path + bugfix → at least medium unless already higher
    if result.risk_level == "low" and is_bugfix:
        if any(h in files_l for h in CORE_PATH_HINTS):
            result.risk_level = "medium"
            if not (result.risk_rationale or "").strip():
                result.risk_rationale = (
                    "Core component bugfix affecting system invariants; "
                    "non-local semantic impact."
                )

    # Drop banned generic risk language
    cleaned = []
    for r in result.potential_risks or []:
        low = r.lower()
        if any(b in low for b in BANNED_RISK_PHRASES):
            continue
        cleaned.append(r)
    result.potential_risks = cleaned

    # has_tests / has_docs from files if model missed them
    if not result.has_tests:
        result.has_tests = any(
            "test" in f.lower() or f.lower().endswith("_test.py")
            for f in (files or [])
        )
    if not result.has_docs:
        result.has_docs = any(
            f.lower().endswith((".md", ".rst", ".txt"))
            and "test" not in f.lower()
            for f in (files or [])
        )

    return result


def pr_understanding_agent(state: ReviewState) -> dict:
    """
    First agent in the review pipeline.
    Analyzes the PR title, body, and changed files to produce a structured understanding.
    """

    files = state.get("files_changed") or []
    body = state.get("body") or ""

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior maintainer doing first-pass analysis of a GitHub PR.
You do NOT approve or reject. You produce structured understanding for specialist reviewers.

Rules:
1. Summary must state the CAUSAL chain when this is a bugfix (what went wrong → why → what the fix changes). Prefer concrete mechanisms (overwrite, sort order, API contract) over vague "improves handling".
2. risk_level reflects blast radius and semantic impact, NOT diff size.
   - Core graph/build/runtime/auth paths that change invariants → medium or high even if the diff is small.
   - risk_rationale must justify the level in one sentence.
3. potential_risks must be SPECIFIC to this change (named behaviors, cases). Ban phrases like "subtle bugs", "edge cases", "thoroughly tested", "may interact poorly".
4. Extract architectural_assumptions the PR relies on (even if implicit).
5. Extract design_tradeoffs and anything the author explicitly leaves out of scope.
6. verification_targets must be concrete checks (behaviors/cases), not "review the tests".
7. affected_areas = system impact (consumers/invariants), not renamed filenames.
8. has_tests / has_docs from files_changed and body only.
9. For bug fixes, fill bug_mechanism: stored state, write path, ordering, what was lost."""),

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

Produce a structured PRUnderstanding JSON matching the schema.

For bug fixes, bug_mechanism must answer: what stored state, what write path, what ordering, what was lost.
If the body mentions deferred alternatives (MultiGraph, merge strategies), put them in out_of_scope_noted.

Also cover:
1. Main purpose (causal if bugfix)
2. change_type categories (feature, bugfix, refactor, docs, test, config, dependency, api, ui, performance, security, chore)
3. risk_level + risk_rationale
4. System impact (affected_areas)
5. focus_areas for specialist reviewers
6. verification_targets (concrete)
7. architectural_assumptions and design_tradeoffs
8. potential_risks (specific only)
9. has_tests / has_docs"""),
    ]).format(
        title=state.get("title", ""),
        body=body or "No description provided.",
        files_changed="\n".join(files),
        diff=(state.get("full_diff") or "")[:12000],
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=PRUnderstanding,
        capability="reasoning",
        agent_name="PRUnderstandingAgent",
    )

    # If gateway returns dict instead of model, normalize
    if isinstance(result, dict):
        result = PRUnderstanding.model_validate(result)

    result = refine_understanding(result, files=files, body=body)

    return {
        "pr_understanding": result.model_dump(),
        "traces": [{
            "agent": "PRUnderstandingAgent",
            "output": result.model_dump_json(indent=2),
        }],
    }