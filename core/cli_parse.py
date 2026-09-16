"""Parse a PR review target. No live owner/repo hardcoded."""

from __future__ import annotations

import re

_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)"
    r"(?:/[^\s]*)?(?:[?#]\S*)?$",
    re.I,
)
_HOSTLESS_RE = re.compile(
    r"^(?:www\.)?github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)"
    r"(?:/[^\s]*)?(?:[?#]\S*)?$",
    re.I,
)
_HASH_RE = re.compile(r"^([^/\s]+)/([^/#\s]+)#(\d+)$")
_SPACE_RE = re.compile(r"^([^/\s]+)/([^/\s]+)\s+(\d+)$")

_USAGE = "Expected owner/repo N, owner/repo#N, or https://github.com/owner/repo/pull/N"


def parse_review_target(s: str) -> tuple[str, int]:
    """Return (owner/repo, pr_number) from a CLI/wizard target string."""
    raw = re.sub(r"\s+", " ", (s or "").strip())
    if not raw:
        raise ValueError(_USAGE)

    raw = raw.rstrip("/")
    for rx in (_URL_RE, _HOSTLESS_RE, _HASH_RE, _SPACE_RE):
        m = rx.match(raw)
        if m:
            owner, name, number = m.group(1), m.group(2), int(m.group(3))
            if number <= 0:
                raise ValueError("PR number must be positive.")
            repo = f"{owner}/{name}"
            if name.lower().endswith(".git"):
                repo = f"{owner}/{name[:-4]}"
            return repo, number

    raise ValueError(_USAGE)
