from langchain_core.prompts import ChatPromptTemplate
from core.state import ReviewState
from core.models import PRAnalysis
from core.gateway import gateway
import re
from typing import Any


def _units_or_diff(state: dict, full_diff: str, max_chars: int) -> str:
    from core.change_units import specialist_code_view

    view = specialist_code_view(state, max_chars=max_chars)
    if view and view not in ("(no change units)", "(no diff)"):
        return view
    if state.get("change_units") is not None:
        return view or "(no change units)"
    return (full_diff or "")[:max_chars]


CORE_PATH_HINTS = (
    "build.py",
    "graph",
    "runtime",
    "auth",
    "db",
    "migrate",
    "cache",
    "security",
)


def analyze_diff(diff: str, files: list[str]) -> dict:
    """Deterministic parser for exact metadata from diff."""
    insertions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            insertions += 1
        elif line.startswith("-"):
            deletions += 1

    suffixes = {f.split(".")[-1].lower() for f in files if "." in f}
    lang_map = {
        "py": "Python",
        "js": "JavaScript",
        "ts": "TypeScript",
        "java": "Java",
        "go": "Go",
        "rs": "Rust",
        "cpp": "C++",
        "c": "C",
        "md": "Markdown",
        "yaml": "YAML",
        "yml": "YAML",
        "json": "JSON",
        "toml": "TOML",
    }
    languages = sorted({lang_map[s] for s in suffixes if s in lang_map})

    tests = any("test" in f.lower() for f in files)
    docs = any(f.lower().endswith(".md") for f in files)
    configs = any(
        any(
            x in f.lower()
            for x in [
                "dockerfile",
                "pyproject",
                "requirements",
                "package.json",
                ".github",
                ".yaml",
                ".yml",
                "moa_config",
                "settings",
            ]
        )
        for f in files
    )

    return {
        "insertions": insertions,
        "deletions": deletions,
        "languages": languages,
        "tests_added_or_modified": tests,
        "documentation_changed": docs,
        "config_changed": configs,
    }


def extract_functions(diff: str) -> dict:
    """
    Extract added/modified functions + module constants from unified diff.

    Handles:
    - +def / -def
    - body edits under context `def` lines
    - @@ hunk headers that include `def name` (when context def is omitted)
    """
    HUNK_HEADER = re.compile(r"^@@[^@]*@@\s*(.*)$")
    DEF_ANY = re.compile(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    PLUS_DEF = re.compile(r"^\+\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    MINUS_DEF = re.compile(r"^\-\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    # Module constant: _FOO or FOO_BAR (len >= 3) — not single-letter G
    PLUS_CONST = re.compile(r"^\+\s*([A-Z_][A-Z0-9_]{2,})\s*=")

    added_defs: set[str] = set()
    removed_defs: set[str] = set()
    touched_by_body: set[str] = set()
    constants_added: set[str] = set()
    current_func: str | None = None

    def _is_test(name: str) -> bool:
        n = name.lower()
        return n.startswith("test_") or n.startswith("_test")

    for line in diff.splitlines():
        if line.startswith(("diff ", "index ")):
            current_func = None
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            current_func = None
            continue

        # @@ -a,b +c,d @@ def foo(
        hm = HUNK_HEADER.match(line)
        if hm:
            tail = hm.group(1) or ""
            dm = DEF_ANY.search(tail)
            if dm:
                current_func = dm.group(1)
            continue

        m = PLUS_DEF.match(line)
        if m:
            added_defs.add(m.group(1))
            current_func = m.group(1)
            continue

        m = MINUS_DEF.match(line)
        if m:
            removed_defs.add(m.group(1))
            current_func = m.group(1)
            continue

        content = line[1:] if line[:1] in " +-" else line
        dm2 = re.match(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", content)
        if dm2:
            current_func = dm2.group(1)

        cm = PLUS_CONST.match(line)
        if cm:
            name = cm.group(1)
            if name.startswith("_") or (name.isupper() and len(name) >= 3):
                constants_added.add(name)

        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            if current_func and not PLUS_DEF.match(line) and not MINUS_DEF.match(line):
                touched_by_body.add(current_func)

    truly_added = sorted(added_defs - removed_defs)
    truly_modified = sorted(
        (removed_defs & added_defs) | (touched_by_body - set(truly_added))
    )

    return {
        "added_functions": [n for n in truly_added if not _is_test(n)],
        "modified_functions": [n for n in truly_modified if not _is_test(n)],
        "added_test_functions": [n for n in truly_added if _is_test(n)],
        "modified_test_functions": [n for n in truly_modified if _is_test(n)],
        "constants_added": sorted(constants_added),
    }


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
)

def boost_modified_from_diff(
    diff: str, files: list[str], modified: list[str], added: list[str] | None = None
) -> list[str]:
    """
    Generic fallback when hunk context header omits the enclosing def or class.
    Scans diff context and modification lines for symbol definitions, ensuring
    functions in added_functions are not duplicated into modified_functions.
    """
    out = set(modified)
    added_set = set(added or [])
    for line in diff.splitlines():
        if not line.startswith(("---", "+++")):
            m_def = re.search(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if m_def and not m_def.group(1).startswith("test_"):
                out.add(m_def.group(1))
            m_cls = re.search(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b", line)
            if m_cls and not m_cls.group(1).startswith("Test"):
                out.add(m_cls.group(1))

    return sorted(out - added_set)


def classify_high_risk_files(files: list[str]) -> tuple[list[str], dict[str, str]]:
    high: list[str] = []
    reasons: dict[str, str] = {}
    for f in files:
        fl = f.lower()
        if "test" in fl:
            continue
        if any(h in fl for h in CORE_PATH_HINTS):
            high.append(f)
            reasons[f] = (
                f"Core-path module ({f}); structural or invariant changes here "
                f"can affect downstream consumers."
            )
    return high, reasons


def pr_analysis_agent(state: ReviewState) -> dict:
    """Deterministic metadata + light LLM semantic interpretation."""

    files = list(state.get("files_changed") or [])
    diff = state.get("full_diff") or ""

    # --- Phase A: deterministic facts (source of truth) ---
    deterministic: dict[str, Any] = analyze_diff(diff, files)
    funcs = extract_functions(diff)
    funcs["modified_functions"] = boost_modified_from_diff(
        diff, files, funcs["modified_functions"], funcs["added_functions"]
    )
    deterministic.update(funcs)
    deterministic["changed_files"] = files

    high, reasons = classify_high_risk_files(files)
    deterministic["high_risk_files"] = high
    deterministic["high_risk_reasons"] = reasons

    # --- Phase B: LLM fills semantic fields only ---
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a senior engineer doing semantic PR analysis.

You receive DETERMINISTIC facts (files, functions, constants). Trust them.

Your job is ONLY to produce:
- logic_changes: algorithms, tables, control-flow changes
- behavior_changes: old → new observable semantics
- review_hotspots: symbols/areas specialists should inspect
- architectural_changes: policies / invariants (not new modules only)

Rules:
- NEVER invent function or class names.
- Only refer to symbols from the deterministic lists or the diff.
- Be concrete, not vague.
- If unsure, use empty lists."""),
        ("human", """PR Title: {title}

PR Body: {body}

Files Changed:
{files_changed}

Deterministic Analysis:
{deterministic}

Change units (hunks — cite file and start_line from CU headers):
{diff}

Fill logic_changes, behavior_changes, review_hotspots, architectural_changes only.
Do not contradict deterministic function lists."""),
    ]).format(
        title=state.get("title", ""),
        body=state.get("body", "") or "",
        files_changed="\n".join(files),
        deterministic=deterministic,
        diff=_units_or_diff(state, diff, 8000),
    )

    try:
        result = gateway.generate_structured(
            prompt=prompt,
            schema=PRAnalysis,
            capability="reasoning",
            agent_name="PRAnalysisAgent",
        )
        if isinstance(result, dict):
            semantic = result
        else:
            semantic = result.model_dump()
    except Exception:
        semantic = {}

    # --- Merge: deterministic always wins on structural facts ---
    analysis = {**semantic, **deterministic}

    analysis.setdefault("modified_classes", [])
    analysis.setdefault("logic_changes", semantic.get("logic_changes") or [])
    analysis.setdefault("behavior_changes", semantic.get("behavior_changes") or [])
    analysis.setdefault("review_hotspots", semantic.get("review_hotspots") or [])
    analysis.setdefault(
        "architectural_changes", semantic.get("architectural_changes") or []
    )
    analysis.setdefault("design_assumptions", semantic.get("design_assumptions") or [])
    analysis.setdefault("downstream_impacts", semantic.get("downstream_impacts") or [])
    analysis.setdefault(
        "behavioral_invariants", semantic.get("behavioral_invariants") or []
    )
    analysis.setdefault("high_risk_reasons", reasons)

    for key in (
        "changed_files",
        "added_functions",
        "modified_functions",
        "added_test_functions",
        "modified_test_functions",
        "constants_added",
        "insertions",
        "deletions",
        "languages",
        "tests_added_or_modified",
        "documentation_changed",
        "config_changed",
        "high_risk_files",
        "high_risk_reasons",
    ):
        if key in deterministic:
            analysis[key] = deterministic[key]

    return {
        "pr_analysis": analysis,
        "traces": [{
            "agent": "PRAnalysisAgent",
            "output": str(analysis),
        }],
    }