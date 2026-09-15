"""Map a candidate onto a GitHub RIGHT-side line. No line → not a Comment."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from core.pr_facts import normalize_path
from core.runtime.models import Candidate
from core.verification.diff_index import DiffIndex

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


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
    start = candidate.start_line or None
    if start is not None:
        try:
            start_i = int(start)
        except (TypeError, ValueError):
            start_i = 0
        if start_i < 1:
            start = None
        else:
            start = start_i
    tokens: List[str] = []
    if candidate.symbol:
        tokens.append(str(candidate.symbol))
    blob = f"{candidate.title or ''} {candidate.claim or ''}"
    tokens.extend(_TOKEN_RE.findall(blob))
    if extra_tokens:
        tokens.extend(str(t) for t in extra_tokens if t)
    line = index.line_for_finding(
        path,
        start_line=start,
        hunk_header="",
        tokens=tokens,
    )
    if line is None:
        return None
    try:
        n = int(line)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None
