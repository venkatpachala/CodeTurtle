"""Deterministic PR facts from GitHub files + diff. No LLM. No repo-specific rules."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{2,}")
_SYM_RE = re.compile(
    r"(?:(?:async\s+)?def|class|function|const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)"
)

# Generic English / review-plan words — not evidence of a real symbol.
_QUESTION_STOP = {
    "the",
    "and",
    "for",
    "how",
    "what",
    "this",
    "that",
    "with",
    "from",
    "code",
    "related",
    "definition",
    "callers",
    "downstream",
    "usages",
    "tests",
    "covering",
    "existing",
    "changed",
    "logic",
    "purpose",
    "helper",
    "constant",
    "implementation",
    "invariants",
    "handles",
    "parameters",
    "return",
    "values",
    "error",
    "conditions",
    "affected",
    "consumers",
    "files",
    "file",
    "path",
    "paths",
    "symbol",
    "symbols",
    "function",
    "functions",
    "class",
    "module",
    "intent",
    "semantic",
    "review",
    "missing",
    "regression",
    "behavior",
    "where",
    "when",
    "into",
    "about",
    "does",
    "not",
    "are",
    "was",
    "were",
    "has",
    "have",
    "its",
    "their",
    "new",
    "old",
    "use",
    "uses",
    "used",
    "using",
    "test",
    "testing",
}


def normalize_path(p: str) -> str:
    return (p or "").replace("\\", "/").strip().strip('"').strip("'")


LOCK_NAMES = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "composer.lock",
    "Gemfile.lock",
    "Pipfile.lock",
    "uv.lock",
    "go.sum",
)

SOURCE_EXTS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".cpp",
    ".c",
    ".rb",
    ".php",
    ".swift",
)


def is_lockfile(path: str) -> bool:
    p = normalize_path(path)
    base = p.split("/")[-1]
    return any(base == n or p.endswith("/" + n) for n in LOCK_NAMES)


def is_source_file(path: str) -> bool:
    p = normalize_path(path).lower()
    return any(p.endswith(ext) for ext in SOURCE_EXTS)


def _is_docs_or_trivia(path: str) -> bool:
    p = normalize_path(path).lower()
    base = p.split("/")[-1]
    if base in {".gitignore", "license", "makefile", ".dockerignore", "wordlist.txt"}:
        return True
    return (
        p.endswith((".md", ".rst", ".txt"))
        or "docs/" in p
        or base.startswith(".")
    )


def classify_change_set(files_changed: Optional[List[str]] = None) -> Dict[str, Any]:
    """Deterministic PR class from files_changed only. No LLM. No repo rules."""
    files = [normalize_path(f) for f in (files_changed or []) if f]
    lock_files = [f for f in files if is_lockfile(f)]
    source_files = [f for f in files if is_source_file(f)]

    if source_files and lock_files:
        classification = "mixed"
    elif source_files:
        classification = "source"
    elif lock_files:
        extras = [f for f in files if f not in lock_files]
        if not extras or all(_is_docs_or_trivia(e) for e in extras):
            classification = "lockfile-only"
        else:
            classification = "other"
    else:
        classification = "other"

    return {
        "classification": classification,
        "lock_files": lock_files,
        "source_files": source_files,
    }


def build_pr_facts(
    *,
    title: str = "",
    body: str = "",
    files_changed: Optional[List[str]] = None,
    full_diff: str = "",
    pr_number: Optional[int] = None,
    repo: str = "",
) -> Dict[str, Any]:
    """Deterministic facts from the real PR. No LLM. No repo-specific rules."""
    files = [normalize_path(f) for f in (files_changed or []) if f]
    files = list(dict.fromkeys(files))

    by_ext = Counter()
    for f in files:
        name = f.split("/")[-1]
        if "." in name:
            by_ext["." + name.split(".")[-1].lower()] += 1
        else:
            by_ext["(noext)"] += 1

    diff = full_diff or ""
    paths_in_diff = _paths_from_diff(diff)
    diff_stat = _diffstat(diff, paths_in_diff=paths_in_diff)

    all_paths = list(dict.fromkeys(files + paths_in_diff))
    kind = classify_change_set(files)

    return {
        "repo": repo,
        "pr_number": pr_number,
        "title": title or "",
        "body_excerpt": (body or "")[:800],
        "files_changed": files,
        "paths_in_diff": paths_in_diff,
        "all_changed_paths": all_paths,
        "file_count": len(files),
        "extension_counts": dict(by_ext),
        "diff_bytes": len(diff.encode("utf-8", errors="ignore")),
        "diff_stat": diff_stat,
        "classification": kind["classification"],
        "lock_files": kind["lock_files"],
        "source_files": kind["source_files"],
        "grounding_rules": [
            "Only claim a file was modified if it appears in files_changed or paths_in_diff.",
            "Every finding must cite at least one concrete path from all_changed_paths.",
            "If title/body conflict with files_changed+diff, trust files_changed+diff.",
            "Graphify context is related structure, not proof of what this PR changed.",
            "If evidence is weak, mark confidence low or say uncertain — do not invent edits.",
            "If classification is lockfile-only, describe a lockfile/dependency lock update, not a new feature.",
        ],
    }


def allowed_paths(facts: Dict[str, Any] | None) -> List[str]:
    """Union of GitHub files_changed and paths parsed from the diff."""
    facts = facts or {}
    out: List[str] = []
    for key in ("files_changed", "paths_in_diff", "all_changed_paths"):
        for p in facts.get(key) or []:
            n = normalize_path(str(p))
            if n:
                out.append(n)
    return list(dict.fromkeys(out))


def _strip_ab_prefix(p: str) -> str:
    p = normalize_path(p)
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    return p


def _paths_from_diff(diff: str) -> List[str]:
    """Collect unique file paths from diff --git / +++ / --- headers."""
    paths: List[str] = []
    for line in (diff or "").splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            for part in parts[2:]:
                p = _strip_ab_prefix(part)
                if p and p != "/dev/null":
                    paths.append(p)
        elif line.startswith("+++ b/"):
            p = _strip_ab_prefix(line[4:].strip())
            if p and p != "/dev/null":
                paths.append(p)
        elif line.startswith("--- a/"):
            p = _strip_ab_prefix(line[4:].strip())
            if p and p != "/dev/null":
                paths.append(p)
        elif line.startswith("+++ ") or line.startswith("--- "):
            rest = line[4:].strip()
            if not rest or rest == "/dev/null":
                continue
            # GitHub-style headers without a/ b/ prefix, e.g. `--- api/foo.py`
            p = _strip_ab_prefix(rest)
            if p and p != "/dev/null" and (
                "/" in p or "." in p.split("/")[-1] or p.endswith(".py")
            ):
                paths.append(p)
    return list(dict.fromkeys(paths))


def _diffstat(diff: str, paths_in_diff: Optional[List[str]] = None) -> Dict[str, int]:
    """Honest telemetry: count files from diff --git, +++ b/, --- a/ (unique)."""
    add = del_ = hunks = 0
    git_headers = 0
    for line in (diff or "").splitlines():
        if line.startswith("diff --git "):
            git_headers += 1
        elif line.startswith("@@"):
            hunks += 1
        elif line.startswith("+") and not line.startswith("+++"):
            add += 1
        elif line.startswith("-") and not line.startswith("---"):
            del_ += 1

    paths = list(paths_in_diff) if paths_in_diff is not None else _paths_from_diff(diff)
    files_in_diff = len(paths) if paths else git_headers
    return {
        "additions": add,
        "deletions": del_,
        "hunks": hunks,
        "files_in_diff": files_in_diff,
    }


def extract_diff_symbols(diff: str) -> List[str]:
    """Identifiers from `def` / `class` / `function` (and similar) in the diff text."""
    found: List[str] = []
    for m in _SYM_RE.finditer(diff or ""):
        found.append(m.group(1))
    return list(dict.fromkeys(found))


def format_pr_facts_for_prompt(facts: Dict[str, Any]) -> str:
    lines = [
        "DETERMINISTIC PR FACTS (from GitHub API + diff; trust over free-form title spin):",
        f"- repo: {facts.get('repo')}",
        f"- pr: #{facts.get('pr_number')}",
        f"- title: {facts.get('title')}",
        f"- file_count: {facts.get('file_count')}",
        f"- diff_bytes: {facts.get('diff_bytes')}",
        f"- diff_stat: {facts.get('diff_stat')}",
        f"- extension_counts: {facts.get('extension_counts')}",
        f"- classification: {facts.get('classification')}",
        f"- lock_files: {facts.get('lock_files') or []}",
        f"- source_files: {facts.get('source_files') or []}",
        "- files_changed:",
    ]
    for p in facts.get("files_changed") or []:
        lines.append(f"  - {p}")
    if facts.get("paths_in_diff"):
        lines.append("- paths_in_diff:")
        for p in facts["paths_in_diff"][:50]:
            lines.append(f"  - {p}")
    lines.append("- grounding_rules:")
    for r in facts.get("grounding_rules") or []:
        lines.append(f"  - {r}")
    return "\n".join(lines)


def finding_evidence_grounded(evidence: List[Any], allowed: List[str]) -> bool:
    """True if at least one evidence string matches a real changed path."""
    if not evidence or not allowed:
        return False
    allowed_n = [normalize_path(a) for a in allowed]
    for e in evidence:
        s = normalize_path(str(e))
        s_l = s.lower()
        s_base = s_l.split("/")[-1]
        for a in allowed_n:
            if not a:
                continue
            a_l = a.lower()
            if s_l == a_l or s_l.endswith("/" + a_l) or a_l.endswith("/" + s_l):
                return True
            if s_base and s_base == a_l.split("/")[-1]:
                return True
    return False


def _has_token(text: str, token: str) -> bool:
    """Whole-token match (no FakeCursor hiding inside other words)."""
    if not text or not token or len(token) < 3:
        return False
    return (
        re.search(
            r"(?i)(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])",
            text,
        )
        is not None
    )


def _interesting_idents(text: str) -> List[str]:
    out: List[str] = []
    for m in _IDENT_RE.finditer(text or ""):
        ident = m.group(0)
        low = ident.lower()
        if low in _QUESTION_STOP or len(ident) < 4:
            continue
        if ident[0].isupper() or "_" in ident or "." in ident:
            out.append(ident)
        elif any(
            ident.endswith(ext) for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs")
        ):
            out.append(ident)
    return out


def question_grounded_in_pr(
    question: str,
    files_changed: Optional[Iterable[str]] = None,
    full_diff: str = "",
) -> bool:
    """Keep a planner question only if it shares a changed-file basename or a diff token.

    Any ungrounded CamelCase / snake_case symbol (FakeConnection, FakeCursor)
    drops the question even if a real symbol is also mentioned.
    """
    q = (question or "").strip()
    if not q:
        return False
    q_norm = q.replace("\\", "/")
    ql = q_norm.lower()
    files = [normalize_path(str(f)) for f in (files_changed or []) if f]
    bases = [f.split("/")[-1].lower() for f in files if f]
    stems = [b.rsplit(".", 1)[0] for b in bases if b]

    shares_basename = False
    for f, base, stem in zip(files, bases, stems):
        if base and len(base) >= 3 and base in ql:
            shares_basename = True
            break
        if len(f) >= 5 and f.lower() in ql:
            shares_basename = True
            break
        if len(stem) > 3 and stem in ql:
            shares_basename = True
            break

    excerpt = (full_diff or "")[:12000]
    diff_tokens = {s.lower() for s in extract_diff_symbols(excerpt)}
    for ident in _interesting_idents(excerpt):
        diff_tokens.add(ident.lower())
        diff_tokens.add(ident.lower().split(".")[-1])

    grounded_names = set(diff_tokens)
    grounded_names.update(bases)
    grounded_names.update(stems)

    shares_diff_token = False
    ungrounded: List[str] = []
    for ident in _interesting_idents(q_norm):
        low = ident.lower()
        last = low.split(".")[-1]
        if (
            low in grounded_names
            or last in grounded_names
            or _has_token(excerpt, ident)
            or _has_token(excerpt, last)
        ):
            shares_diff_token = True
        else:
            ungrounded.append(ident)

    if ungrounded:
        return False
    return shares_basename or shares_diff_token


def dedupe_near_duplicate_questions(questions: List[str]) -> List[str]:
    """Drop questions that repeat the same identifier set / long prefix."""
    unique: List[str] = []
    seen_keys: List[set[str]] = []
    seen_norm: List[str] = []
    for q in questions:
        s = re.sub(r"\s+", " ", (q or "").strip().lower())
        if not s:
            continue
        idents = {m.group(0).lower() for m in _IDENT_RE.finditer(s)} - _QUESTION_STOP
        skip = False
        for prev in seen_norm:
            if s == prev or (len(s) > 40 and (s[:60] in prev or prev[:60] in s)):
                skip = True
                break
        if not skip and idents:
            for prev_ids in seen_keys:
                if not prev_ids:
                    continue
                overlap = len(idents & prev_ids) / max(1, len(idents | prev_ids))
                if overlap >= 0.8:
                    skip = True
                    break
        if skip:
            continue
        unique.append(q.strip())
        seen_keys.append(idents)
        seen_norm.append(s)
    return unique
