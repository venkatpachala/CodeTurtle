"""Optional deterministic rules. source=rule; Positioner+Reflector still apply."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

from core.pr_facts import is_source_file, normalize_path
from core.runtime.models import Bundle, Candidate

_EVAL_RE = re.compile(r"\beval\s*\(")
_BARE_EXCEPT_RE = re.compile(r"^\s*except\s*:", re.M)


def _unit_fields(u: Any) -> tuple[str, str, int]:
    if isinstance(u, dict):
        path = normalize_path(str(u.get("path") or ""))
        excerpt = str(u.get("excerpt") or "")
        try:
            start = int(u.get("start_line") or 0)
        except (TypeError, ValueError):
            start = 0
        return path, excerpt, start
    path = normalize_path(str(getattr(u, "path", "") or ""))
    excerpt = str(getattr(u, "excerpt", "") or "")
    try:
        start = int(getattr(u, "start_line", 0) or 0)
    except (TypeError, ValueError):
        start = 0
    return path, excerpt, start


def _added_text(excerpt: str) -> str:
    lines = []
    for ln in (excerpt or "").splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            lines.append(ln[1:])
        elif not ln.startswith(("-", "@@", "\\")):
            if not ln.startswith("diff ") and not ln.startswith("index "):
                lines.append(ln[1:] if ln.startswith(" ") else ln)
    return "\n".join(lines)


def _regex_candidates(bundles: Sequence[Bundle]) -> List[Candidate]:
    out: List[Candidate] = []
    for b in bundles or []:
        for u in b.units or []:
            path, excerpt, start = _unit_fields(u)
            if not path or not path.endswith(".py"):
                continue
            added = _added_text(excerpt)
            if _EVAL_RE.search(added):
                out.append(
                    Candidate(
                        bundle_id=b.id,
                        file=path,
                        symbol="",
                        start_line=start,
                        title="eval() in changed code",
                        claim="Added code calls eval(",
                        severity="high",
                        source="rule",
                        evidence_paths=[path],
                    )
                )
            if _BARE_EXCEPT_RE.search(added):
                out.append(
                    Candidate(
                        bundle_id=b.id,
                        file=path,
                        symbol="",
                        start_line=start,
                        title="bare except:",
                        claim="Added code uses a bare except:",
                        severity="medium",
                        source="rule",
                        evidence_paths=[path],
                    )
                )
    return out


def _ruff_candidates(
    files_changed: Sequence[str],
    *,
    bundles: Sequence[Bundle],
    repo_dir: Optional[str] = None,
) -> List[Candidate]:
    if shutil.which("ruff") is None:
        return []
    py_files = [
        normalize_path(p)
        for p in files_changed
        if p and is_source_file(p) and p.replace("\\", "/").endswith(".py")
    ]
    if not py_files:
        return []
    cwd = Path(repo_dir) if repo_dir else None
    existing: List[str] = []
    for p in py_files:
        if cwd is None:
            continue
        if (cwd / p).is_file():
            existing.append(p)
    if not existing:
        return []
    try:
        proc = subprocess.run(
            ["ruff", "check", "--output-format", "json", *existing],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    by_file = {normalize_path(p): b.id for b in bundles for p in b.paths}
    out: List[Candidate] = []
    allowed = {normalize_path(p) for p in py_files}
    for it in items:
        if not isinstance(it, dict):
            continue
        fp = normalize_path(str(it.get("filename") or it.get("file") or ""))
        if cwd and fp:
            try:
                fp = normalize_path(str(Path(fp).resolve().relative_to(cwd.resolve())))
            except Exception:
                fp = normalize_path(fp)
        if fp not in allowed:
            base = fp.split("/")[-1]
            hit = next((a for a in allowed if a.split("/")[-1] == base), "")
            if not hit:
                continue
            fp = hit
        loc = it.get("location") if isinstance(it.get("location"), dict) else {}
        try:
            row = int(loc.get("row") or it.get("row") or 0)
        except (TypeError, ValueError):
            row = 0
        code = str(it.get("code") or "ruff")
        msg = str(it.get("message") or code)
        out.append(
            Candidate(
                bundle_id=by_file.get(fp, "B-001"),
                file=fp,
                symbol="",
                start_line=row,
                title=f"ruff {code}",
                claim=msg,
                severity="medium",
                source="rule",
                evidence_paths=[fp],
            )
        )
    return out


def run_rule_engine(
    bundles: Sequence[Bundle],
    *,
    files_changed: Iterable[str] | None = None,
    full_diff: str = "",
    repo_dir: Optional[str] = None,
) -> List[Candidate]:
    """Regex always. Ruff only if the binary is on PATH and files exist on disk."""
    _ = full_diff
    files = [normalize_path(p) for p in (files_changed or []) if p]
    out: List[Candidate] = []
    out.extend(_regex_candidates(bundles))
    out.extend(
        _ruff_candidates(files, bundles=bundles, repo_dir=repo_dir)
    )
    return out
