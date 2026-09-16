"""Map a candidate onto a GitHub RIGHT-side line. No line → not a Comment."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from core.pr_facts import normalize_path
from core.runtime.models import Candidate
from core.verification.diff_index import DiffIndex

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def line_for_finding(diff_index: DiffIndex, file: str, existing_code: str) -> Optional[int]:
    cand = Candidate(bundle_id="", file=file, existing_code=existing_code or "")
    return position_candidate(cand, diff_index)


def position_candidate(
    candidate: Candidate,
    index: DiffIndex,
    *,
    extra_tokens: Optional[Iterable[str]] = None,
) -> Optional[int]:
    """Reuse DiffIndex RIGHT-side line logic from inline comments."""
    path = normalize_path(candidate.file)
    if not path or index is None:
        return None
    snippet = str(getattr(candidate, "existing_code", "") or "")
    snip_line = index.line_for_snippet(path, snippet)
    if snip_line and int(snip_line) > 1:
        print(f"[Positioner] file={path} line={int(snip_line)}")
        return int(snip_line)
    if snippet.strip():
        print(f"[Positioner] no_line reason=snippet_not_in_hunk file={path}")
        return None
    tokens: List[str] = []
    if candidate.symbol:
        tokens.append(str(candidate.symbol))
    blob = f"{candidate.title or ''} {candidate.claim or ''}"
    tokens.extend(_TOKEN_RE.findall(blob))
    if extra_tokens:
        tokens.extend(str(t) for t in extra_tokens if t)
    line = index.line_for_finding(
        path,
        start_line=None,
        hunk_header="",
        tokens=tokens,
    )
    if line is None:
        print(f"[Positioner] no_line reason=snippet_not_in_hunk file={path}")
        return None
    try:
        n = int(line)
    except (TypeError, ValueError):
        return None
    if n <= 1:
        print(f"[Positioner] no_line reason=snippet_not_in_hunk file={path}")
        return None
    print(f"[Positioner] file={path} line={n}")
    return n
