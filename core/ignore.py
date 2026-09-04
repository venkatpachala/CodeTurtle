"""Glob ignore_paths from .codeturtle.yaml. Supports ** across directories."""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence


def _glob_to_re(pattern: str) -> re.Pattern[str]:
    i = 0
    out: List[str] = ["^"]
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern[i] == "*":
            out.append("[^/]*")
            i += 1
            continue
        if pattern[i] == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(pattern[i]))
        i += 1
    out.append("$")
    return re.compile("".join(out), re.IGNORECASE)


def is_ignored(path: str, patterns: Sequence[str] | None) -> bool:
    p = (path or "").replace("\\", "/").strip().lstrip("./")
    if not p or not patterns:
        return False
    base = p.split("/")[-1]
    for raw in patterns:
        pat = str(raw or "").replace("\\", "/").strip()
        if not pat or pat.startswith("#"):
            continue
        rx = _glob_to_re(pat)
        if rx.match(p) or rx.match(base):
            return True
        if pat.startswith("**/") and _glob_to_re(pat[3:]).match(p):
            return True
    return False


def filter_paths(paths: Iterable[str], patterns: Sequence[str] | None) -> List[str]:
    return [p for p in paths if not is_ignored(p, patterns)]
