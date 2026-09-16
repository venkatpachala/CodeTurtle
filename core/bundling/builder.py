"""Group changed files into review bundles. Deterministic. No LLM."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.change_units import _TEST_BASENAME_RE, unit_kind
from core.pr_facts import (
    _is_docs_or_trivia,
    is_lockfile,
    is_source_file,
    normalize_path,
    source_first_paths,
)
from core.runtime.models import Bundle

MAX_FILES_PER_BUNDLE = 6
MAX_BUNDLES = 4

_JS_TEST_RE = re.compile(r".*\.test\.(ts|tsx|js|jsx)$", re.I)
_GENERIC_DIRS = {
    "cli",
    "src",
    "pkg",
    "lib",
    "app",
    "core",
    "unit",
    "tests",
    "test",
    "api",
    "models",
    "utils",
    "bin",
    "scripts",
    "python",
    "js",
    "ts",
}


def _is_test_path(path: str) -> bool:
    n = normalize_path(path)
    base = n.split("/")[-1]
    if _TEST_BASENAME_RE.match(base or "") or _JS_TEST_RE.match(base or ""):
        return True
    low = f"/{n.lower()}/"
    return "/tests/" in low or n.lower().startswith("tests/")


def _stem(path: str) -> str:
    base = normalize_path(path).split("/")[-1]
    name = base.rsplit(".", 1)[0] if "." in base else base
    low = name.lower()
    if low.startswith("test_"):
        return name[5:]
    if low.endswith("_test"):
        return name[:-5]
    for token in (".test", "_spec", ".spec"):
        idx = low.find(token)
        if idx > 0:
            return name[:idx]
    return name


def _dir_key(path: str) -> str:
    n = normalize_path(path)
    parts = [p for p in n.split("/") if p]
    if len(parts) <= 1:
        return "."
    return "/".join(parts[:-1])


def _last_parent(path: str) -> str:
    parents = [p.lower() for p in normalize_path(path).split("/")[:-1] if p]
    return parents[-1] if parents else ""


def _stem_head(path: str) -> str:
    stem = _stem(path).lower()
    parts = [p for p in stem.split("_") if p]
    return parts[0] if parts and len(parts[0]) >= 4 else ""


def _feature_key(path: str) -> str:
    """hosted_jobs + hosted/ join; jobs.py / trials.py stay separate."""
    n = normalize_path(path)
    last_parent = _last_parent(n)
    stem = _stem(n).lower()
    stem_head = _stem_head(n)
    if last_parent and last_parent not in _GENERIC_DIRS:
        return last_parent
    if stem_head:
        return stem_head
    parents = [p.lower() for p in n.split("/")[:-1] if p]
    for parent in reversed(parents):
        if parent not in _GENERIC_DIRS:
            return parent
    return stem or n


def _as_unit(item: Any) -> Any:
    if item is None:
        return None
    if hasattr(item, "path"):
        return item
    if isinstance(item, dict):
        from core.change_units import ChangeUnit

        return ChangeUnit.model_validate(item)
    return item


def _unit_path(u: Any) -> str:
    if u is None:
        return ""
    if isinstance(u, dict):
        return normalize_path(str(u.get("path") or ""))
    return normalize_path(str(getattr(u, "path", "") or ""))


def _risk_hint(u: Any) -> str:
    if u is None:
        return "none"
    if isinstance(u, dict):
        return str(u.get("risk_hint") or "none")
    return str(getattr(u, "risk_hint", "") or "none")


def _unit_symbols(u: Any) -> List[str]:
    if u is None:
        return []
    if isinstance(u, dict):
        return [str(s) for s in (u.get("symbols") or []) if s]
    return [str(s) for s in (getattr(u, "symbols", None) or []) if s]


def _docs_only(files: Sequence[str], classification: str) -> bool:
    if classification == "docs-only":
        return True
    if classification in ("lockfile-only", "source", "mixed"):
        return False
    kept = [normalize_path(p) for p in files if p]
    if not kept:
        return False
    if any(is_source_file(p) for p in kept):
        return False
    if any(is_lockfile(p) for p in kept):
        return False
    return all(_is_docs_or_trivia(p) or p.lower().endswith(".mdx") for p in kept)


def _keep_file(path: str, *, classification: str, files: Sequence[str]) -> bool:
    n = normalize_path(path)
    if not n:
        return False
    if classification == "lockfile-only":
        return True
    if _docs_only(files, classification):
        return True
    if is_lockfile(n) or _is_docs_or_trivia(n) or n.lower().endswith(".mdx"):
        return False
    return True


def _path_rank(path: str, units_by_path: Dict[str, List[Any]]) -> Tuple[int, int, str]:
    units = units_by_path.get(normalize_path(path), [])
    if any(_risk_hint(u) == "mutation" for u in units):
        return (0, 0, path)
    kind = unit_kind(path)
    rank = {"source": 1, "test": 2, "other": 3, "docs": 4, "lockfile": 5}.get(kind, 6)
    return (rank, 0, path)


def _order_paths(paths: Sequence[str], units_by_path: Dict[str, List[Any]]) -> List[str]:
    uniq = list(dict.fromkeys(normalize_path(p) for p in paths if p))
    sources = [p for p in uniq if not _is_test_path(p)]
    tests = [p for p in uniq if _is_test_path(p)]
    sources.sort(key=lambda p: _path_rank(p, units_by_path))
    out: List[str] = []
    used = set()
    for s in sources:
        out.append(s)
        stem = _stem(s).lower()
        for t in tests:
            if t not in used and _stem(t).lower() == stem:
                out.append(t)
                used.add(t)
    for t in tests:
        if t not in used:
            out.append(t)
    for p in uniq:
        if p not in out:
            out.append(p)
    return out


def _chunk(paths: Sequence[str], size: int = MAX_FILES_PER_BUNDLE) -> List[List[str]]:
    items = list(paths)
    if not items:
        return []
    return [items[i : i + size] for i in range(0, len(items), size)]


def _bundle_kind(paths: Sequence[str]) -> str:
    kinds = [unit_kind(p) for p in paths]
    if "source" in kinds:
        return "source"
    if "test" in kinds:
        return "test"
    if "lockfile" in kinds and not any(k in ("source", "test") for k in kinds):
        return "lockfile"
    if "docs" in kinds and not any(k in ("source", "test") for k in kinds):
        return "docs"
    return "other"


def _group_rank(paths: Sequence[str], units_by_path: Dict[str, List[Any]]) -> Tuple[int, int]:
    mutation = False
    source = False
    test = False
    for p in paths:
        kind = unit_kind(p)
        if kind == "source":
            source = True
        if kind == "test":
            test = True
        for u in units_by_path.get(normalize_path(p), []):
            if _risk_hint(u) == "mutation":
                mutation = True
    if mutation:
        return (0, -len(paths))
    if source:
        return (1, -len(paths))
    if test:
        return (2, -len(paths))
    return (3, -len(paths))


class BundleBuilder:
    """Drop docs/lock on source PRs; group by directory/stem; cap size."""

    def build(
        self,
        *,
        files_changed: Optional[Iterable[str]] = None,
        units: Optional[Sequence[Any]] = None,
        classification: str = "",
        max_bundles: Optional[int] = None,
    ) -> List[Bundle]:
        files = [normalize_path(p) for p in (files_changed or []) if p]
        files = list(dict.fromkeys(files))
        classification = str(classification or "")
        kept = [p for p in files if _keep_file(p, classification=classification, files=files)]

        parsed_units = [u for u in (_as_unit(x) for x in (units or [])) if u is not None]
        units_by_path: Dict[str, List[Any]] = defaultdict(list)
        for u in parsed_units:
            p = _unit_path(u)
            if p:
                units_by_path[p].append(u)

        sources = [p for p in kept if is_source_file(p) and not _is_test_path(p)]
        tests = [p for p in kept if _is_test_path(p)]
        others = [p for p in kept if p not in sources and p not in tests]

        groups: Dict[str, List[str]] = {}

        def _add(key: str, path: str) -> None:
            bucket = groups.setdefault(key, [])
            if path not in bucket:
                bucket.append(path)

        for p in sources:
            _add(_feature_key(p), p)

        source_keys = list(groups.keys())
        for t in tests:
            key = _feature_key(t)
            if key in groups:
                _add(key, t)
                continue
            exact = [s for s in sources if _stem(s).lower() == _stem(t).lower()]
            if exact:
                _add(_feature_key(exact[0]), t)
                continue
            if sources and source_keys:
                _add(source_keys[0], t)
            else:
                _add(key, t)

        for p in others:
            _add(_feature_key(p), p)

        if sources:
            for key in list(groups.keys()):
                paths = list(groups.get(key) or [])
                if paths and all(_is_test_path(p) for p in paths):
                    dest = source_keys[0] if source_keys else key
                    groups.pop(key, None)
                    for t in paths:
                        _add(dest, t)

        ranked_groups = sorted(
            groups.values(),
            key=lambda paths: _group_rank(paths, units_by_path),
        )

        chunks: List[List[str]] = []
        for group in ranked_groups:
            ordered = _order_paths(group, units_by_path)
            chunks.extend(_chunk(ordered, MAX_FILES_PER_BUNDLE))

        cap = max_bundles if max_bundles is not None else MAX_BUNDLES
        try:
            cap = max(1, int(cap))
        except (TypeError, ValueError):
            cap = MAX_BUNDLES
        chunks = chunks[:cap]
        bundles: List[Bundle] = []
        for i, paths in enumerate(chunks, start=1):
            paths = source_first_paths(paths) if any(is_source_file(p) for p in paths) else list(paths)
            b_units: List[Any] = []
            seen = set()
            symbols: List[str] = []
            for p in paths:
                for u in units_by_path.get(p, []):
                    uid = getattr(u, "id", None) or (u.get("id") if isinstance(u, dict) else id(u))
                    if uid in seen:
                        continue
                    seen.add(uid)
                    b_units.append(u)
                    for s in _unit_symbols(u):
                        if s not in symbols:
                            symbols.append(s)
            bundles.append(
                Bundle(
                    id=f"B-{i:03d}",
                    paths=list(paths),
                    units=b_units,
                    symbols=symbols,
                    kind=_bundle_kind(paths),
                )
            )
        for b in bundles:
            print(
                f"[Bundle] {b.id} kind={b.kind} files={','.join(b.paths)}"
            )
        return bundles
