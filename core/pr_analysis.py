from langchain_core.prompts import ChatPromptTemplate
from core.state import ReviewState
from core.models import PRAnalysis
from core.gateway import gateway
import re


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

    suffixes = {f.split('.')[-1].lower() for f in files if '.' in f}
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
        any(x in f.lower() for x in ["dockerfile", "pyproject", "requirements", "package.json", ".github", ".yaml", ".yml", "moa_config", "settings"])
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


def extract_functions(diff: str):
    """Extract added, modified, and test functions from diff."""
    added = set()
    modified = set()
    test_added = set()
    test_modified = set()

    FUNC_PATTERN = re.compile(r'^[+-]\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(')

    for line in diff.splitlines():
        m = FUNC_PATTERN.match(line)
        if not m:
            continue

        name = m.group(1)
        is_test = name.startswith("test_") or "test" in name.lower()

        if line.startswith("+"):
            if is_test:
                test_added.add(name)
            else:
                added.add(name)
        elif line.startswith("-"):
            if is_test:
                test_modified.add(name)
            else:
                modified.add(name)

    # Functions that appear in both are modified
    truly_modified = added & modified
    truly_added = added - modified
    truly_test_modified = test_modified & test_added
    truly_test_added = test_added - test_modified

    return {
        "added_functions": sorted(truly_added),
        "modified_functions": sorted(truly_modified),
        "added_test_functions": sorted(truly_test_added),
        "modified_test_functions": sorted(truly_test_modified)
    }


def pr_analysis_agent(state: ReviewState) -> dict:
    """Deterministic + LLM PR Analysis."""

    # Phase 1: Deterministic parser
    deterministic = analyze_diff(
        state.get("full_diff", ""),
        state.get("files_changed", [])
    )
    deterministic.update(
        extract_functions(state.get("full_diff", ""))
    )

    # Phase 2: LLM for semantic structural analysis ONLY
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert senior software engineer performing semantic PR analysis.

Your job is ONLY to interpret structural changes and explain architectural implications.
Rules:
- NEVER invent functions or classes.
- Use only the supplied deterministic facts.
- If uncertain, return empty lists."""),
        ("human", """PR Title: {title}

PR Body: {body}

Files Changed: {files_changed}

Deterministic Analysis:
{deterministic}

Full Diff (truncated):
{diff}

Explain architectural implications and review focus areas.""")
    ]).format(
        title=state.get("title", ""),
        body=state.get("body", ""),
        files_changed="\n".join(state.get("files_changed", [])),
        deterministic=deterministic,
        diff=(state.get("full_diff") or "")[:8000]
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=PRAnalysis,
        capability="reasoning",
        agent_name="PRAnalysisAgent"
    )

    # Merge deterministic + LLM results
    analysis = result.model_dump()
    analysis.update(deterministic)

    return {
        "pr_analysis": analysis,
        "traces": [{
            "agent": "PRAnalysisAgent",
            "output": str(analysis)
        }]
    }