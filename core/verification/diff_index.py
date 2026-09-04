"""Parse full_diff into per-file hunks. Deterministic. No GitHub. No LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from core.pr_facts import normalize_path

_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)


@dataclass
class Hunk:
    file: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    body: str
    added: str
    removed: str

    @property
    def new_end(self) -> int:
        """Inclusive new-side end line."""
        start = int(self.new_start or 0)
        count = int(self.new_count or 0)
        if count <= 0:
            return start
        return start + count - 1

    @property
    def raw(self) -> str:
        parts: List[str] = []
        if self.header:
            parts.append(self.header)
        if self.body:
            parts.append(self.body)
        return "\n".join(parts)


@dataclass
class DiffIndex:
    files: Set[str] = field(default_factory=set)
    hunks_by_file: Dict[str, List[Hunk]] = field(default_factory=dict)

    def file_set(self) -> Set[str]:
        return set(self.files)

    def hunks_for(self, path: str) -> List[Hunk]:
        hit = self._resolve(path)
        if not hit:
            return []
        return list(self.hunks_by_file.get(hit) or [])

    def line_in_new_file(self, path: str, line: int) -> bool:
        if line is None:
            return False
        try:
            n = int(line)
        except (TypeError, ValueError):
            return False
        for h in self.hunks_for(path):
            end = h.new_start + max(h.new_count, 1)
            if h.new_start <= n < end:
                return True
        return False

    def contains(self, path: str, needle: str) -> bool:
        if not needle:
            return False
        n = needle.lower()
        for h in self.hunks_for(path):
            if n in (h.body or "").lower() or n in (h.added or "").lower() or n in (h.removed or "").lower():
                return True
        return False

    def has_file(self, path: str) -> bool:
        return self._resolve(path) is not None

    def first_added_line(self, hunk: Hunk) -> Optional[int]:
        """RIGHT-side line of the first '+' row in a hunk."""
        n = int(hunk.new_start or 0)
        if n < 1:
            return None
        for raw in (hunk.body or "").splitlines():
            if raw.startswith("-") and not raw.startswith("---"):
                continue
            if raw.startswith("+") and not raw.startswith("+++"):
                return n
            n += 1
        if hunk.new_count > 0 and hunk.new_start >= 1:
            return int(hunk.new_start)
        return None

    def line_for_finding(
        self,
        path: str,
        start_line: Optional[int] = None,
        hunk_header: str = "",
        tokens: Optional[Iterable[str]] = None,
    ) -> Optional[int]:
        """Resolve a GitHub RIGHT-side line, or None (do not guess line 1)."""
        hunks = self.hunks_for(path)
        if not hunks:
            return None
        if start_line is not None:
            try:
                n = int(start_line)
            except (TypeError, ValueError):
                n = 0
            if n >= 1 and self.line_in_new_file(path, n):
                return n
        header = (hunk_header or "").strip()
        toks = [str(t) for t in (tokens or []) if t]
        matched: Optional[Hunk] = None
        if header:
            for h in hunks:
                if (h.header or "").strip() == header or header in (h.header or ""):
                    matched = h
                    break
        if matched is None and toks:
            for h in hunks:
                blob = f"{h.body or ''}\n{h.added or ''}"
                if any(t.lower() in blob.lower() for t in toks):
                    matched = h
                    break
        if matched is not None:
            if matched.new_start >= 1 and matched.new_count > 0:
                return int(matched.new_start)
            return self.first_added_line(matched)
        return self.first_added_line(hunks[0])

    def _resolve(self, path: str) -> Optional[str]:
        p = normalize_path(path)
        if not p:
            return None
        pl = p.lower()
        base = pl.split("/")[-1]
        for a in self.files:
            al = a.lower()
            if pl == al:
                return a
            if pl.endswith("/" + al) or al.endswith("/" + pl):
                return a
            if base and base == al.split("/")[-1]:
                return a
        return None


def _strip_ab(p: str) -> str:
    p = normalize_path(p)
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    return p


def build_diff_index(full_diff: str) -> DiffIndex:
    """Index unified diffs: diff --git / --- a/ / +++ b/ / @@ hunks."""
    idx = DiffIndex()
    current_file: Optional[str] = None
    hunk: Optional[dict] = None

    def flush_hunk() -> None:
        nonlocal hunk
        if hunk and current_file:
            idx.hunks_by_file.setdefault(current_file, []).append(
                Hunk(
                    file=current_file,
                    old_start=hunk["old_start"],
                    old_count=hunk["old_count"],
                    new_start=hunk["new_start"],
                    new_count=hunk["new_count"],
                    header=hunk["header"],
                    body="\n".join(hunk["body"]),
                    added="\n".join(hunk["added"]),
                    removed="\n".join(hunk["removed"]),
                )
            )
        hunk = None

    for raw in (full_diff or "").splitlines():
        if raw.startswith("diff --git "):
            flush_hunk()
            current_file = None
            parts = raw.split()
            for part in parts[2:]:
                p = _strip_ab(part)
                if p and p != "/dev/null":
                    current_file = p
                    idx.files.add(p)
            continue
        if raw.startswith("+++ b/"):
            p = _strip_ab(raw[4:].strip())
            if p and p != "/dev/null":
                current_file = p
                idx.files.add(p)
            continue
        if raw.startswith("--- a/"):
            p = _strip_ab(raw[4:].strip())
            if p and p != "/dev/null":
                idx.files.add(p)
                if current_file is None:
                    current_file = p
            continue
        if raw.startswith("+++ ") or raw.startswith("--- "):
            rest = raw[4:].strip()
            if rest and rest != "/dev/null":
                p = _strip_ab(rest)
                if p and p != "/dev/null":
                    idx.files.add(p)
                    if raw.startswith("+++ "):
                        current_file = p
            continue
        m = _HUNK_RE.match(raw)
        if m:
            flush_hunk()
            hunk = {
                "old_start": int(m.group(1)),
                "old_count": int(m.group(2) or "1"),
                "new_start": int(m.group(3)),
                "new_count": int(m.group(4) or "1"),
                "header": raw.strip(),
                "body": [],
                "added": [],
                "removed": [],
            }
            continue
        if hunk is not None:
            hunk["body"].append(raw)
            if raw.startswith("+") and not raw.startswith("+++"):
                hunk["added"].append(raw[1:])
            elif raw.startswith("-") and not raw.startswith("---"):
                hunk["removed"].append(raw[1:])

    flush_hunk()
    return idx
