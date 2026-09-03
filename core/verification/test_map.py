"""Related-test path heuristic. Repo-agnostic. No execution. No Graphify hops."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from core.pr_facts import is_lockfile, normalize_path

_TRIVIA = (
    ".gitignore",
    "license",
    "makefile",
    ".dockerignore",
    "wordlist.txt",
)

_PATH_RE = re.compile(
    r"[A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx)"
)


def _is_trivia(path: str) -> bool:
    p = normalize_path(path).lower()
    base = p.split("/")[-1]
    return any(t in p or base == t for t in _TRIVIA)


def _is_test_path(path: str) -> bool:
    p = normalize_path(path).lower().replace("\\", "/")
    base = p.split("/")[-1]
    if base.startswith("test_") or base.endswith("_test.py"):
        return True
    if ".test." in base or ".spec." in base:
        return True
    if "/__tests__/" in f"/{p}/" or p.startswith("__tests__/"):
        return True
    if p.startswith("tests/") or "/tests/" in p or p.startswith("test/") or "/test/" in p:
        return True
    return False


def _stem(path: str) -> str:
    base = normalize_path(path).split("/")[-1]
    for ext in (".test", ".spec"):
        # Modal.test.tsx → don't use that as a source stem here
        pass
    if "." not in base:
        return base
    stem = base.rsplit(".", 1)[0]
    # foo.test / foo.spec
    if stem.lower().endswith(".test") or stem.lower().endswith(".spec"):
        stem = stem.rsplit(".", 1)[0]
    return stem


def _parent_dir(path: str) -> str:
    p = normalize_path(path)
    if "/" not in p:
        return ""
    return p.rsplit("/", 1)[0]


def _basename_matches_stem(candidate: str, stem: str) -> bool:
    base = normalize_path(candidate).split("/")[-1]
    bl = base.lower()
    sl = stem.lower()
    if not sl or len(sl) < 2:
        return False
    patterns = (
        f"test_{sl}.py",
        f"{sl}_test.py",
        f"{sl}.test.ts",
        f"{sl}.test.tsx",
        f"{sl}.test.js",
        f"{sl}.test.jsx",
        f"{sl}.spec.ts",
        f"{sl}.spec.tsx",
        f"{sl}.spec.js",
        f"{sl}.spec.jsx",
        f"{sl}.py",  # only accepted under __tests__/
    )
    if bl in patterns:
        # bare stem.py only in __tests__
        if bl == f"{sl}.py":
            return "/__tests__/" in normalize_path(candidate).lower()
        return True
    # test_stem with other ext
    if bl.startswith(f"test_{sl}.") or bl.startswith(f"{sl}_test."):
        return True
    if bl.startswith(f"{sl}.test.") or bl.startswith(f"{sl}.spec."):
        return True
    return False


def related_test_paths(source_file: str, files_changed: List[str] | None) -> List[str]:
    """Subset of files_changed that look like tests for source_file."""
    src = normalize_path(source_file)
    if not src or is_lockfile(src) or _is_trivia(src):
        return []
    if _is_test_path(src):
        return []  # don't map a test to itself as companion

    stem = _stem(src)
    parent = _parent_dir(src)
    hits: List[str] = []
    for raw in files_changed or []:
        cand = normalize_path(str(raw))
        if not cand or cand == src:
            continue
        if is_lockfile(cand) or _is_trivia(cand):
            continue
        if not _is_test_path(cand):
            continue
        cl = cand.lower()
        # sibling test_<basename>
        if parent and _parent_dir(cand) == parent and _basename_matches_stem(cand, stem):
            hits.append(cand)
            continue
        if _basename_matches_stem(cand, stem):
            hits.append(cand)
            continue
        # tests/test_<stem>.py or test/test_<stem>.py (already covered by basename)
        if cl.endswith(f"/test_{stem.lower()}.py") or cl.endswith(f"/test_{stem.lower()}.ts"):
            hits.append(cand)
    return list(dict.fromkeys(hits))


def _neighbor_paths(finding: Dict[str, Any]) -> List[str]:
    blob_parts = [
        " ".join(str(x) for x in (finding.get("investigation_snippets") or [])),
        str(finding.get("reasoning") or ""),
        " ".join(str(x) for x in (finding.get("evidence") or [])),
    ]
    blob = "\n".join(blob_parts).replace("\\", "/")
    found = [normalize_path(m.group(0)) for m in _PATH_RE.finditer(blob)]
    return list(dict.fromkeys(found))


def annotate_tests(
    finding: dict,
    files_changed: Optional[List[str]] = None,
    neighbor_paths: Optional[Iterable[str]] = None,
) -> dict:
    """Sets tests_touched / related_tests. Does not change verification_status."""
    changed = [normalize_path(str(f)) for f in (files_changed or []) if f]
    src = normalize_path(str(finding.get("file") or ""))
    related = related_test_paths(src, changed)

    if not related:
        neigh = list(neighbor_paths) if neighbor_paths is not None else _neighbor_paths(finding)
        neigh_hits = related_test_paths(src, [normalize_path(n) for n in neigh])
        changed_l = {c.lower() for c in changed}
        related = [
            p
            for p in neigh_hits
            if p.lower() in changed_l
            or any(c.lower().endswith("/" + p.split("/")[-1].lower()) for c in changed)
        ]

    finding["related_tests"] = related
    finding["tests_touched"] = bool(related)
    return finding
