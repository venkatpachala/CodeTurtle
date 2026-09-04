"""CI helpers for GitHub Actions (6.3a). No webhook server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional, Tuple

SESSION_FILE = ".current_session"
DEPENDABOT_ACTORS = frozenset(
    {
        "dependabot[bot]",
        "dependabot-preview[bot]",
    }
)


def resolve_github_token(
    environ: Optional[Mapping[str, str]] = None,
    fallback: str = "",
) -> str:
    """CODETURTLE_GITHUB_TOKEN, then GITHUB_TOKEN, then fallback/settings."""
    env = environ if environ is not None else os.environ
    for key in ("CODETURTLE_GITHUB_TOKEN", "GITHUB_TOKEN"):
        v = (env.get(key) or "").strip()
        if v:
            return v
    if fallback.strip():
        return fallback.strip()
    try:
        from config import settings

        return str(getattr(settings, "github_token", "") or "").strip()
    except Exception:
        return ""


def ensure_session(
    path: str = SESSION_FILE,
    *,
    create=None,
) -> str:
    """Return existing session id, or create one (CI has no prior new-session)."""
    p = Path(path)
    if p.is_file():
        sid = p.read_text(encoding="utf-8").strip()
        if sid:
            return sid
    if create is None:
        from core.memory.manager import MemoryManager

        sid = MemoryManager().create_new_session()
    else:
        sid = str(create())
    p.write_text(sid + "\n", encoding="utf-8")
    return sid


def should_skip_pr_review(
    *,
    actor: str = "",
    draft: bool = False,
    review_drafts: bool = False,
) -> Tuple[bool, str]:
    """Default: skip Dependabot and drafts. No review posted."""
    a = (actor or "").strip()
    al = a.lower()
    if a in DEPENDABOT_ACTORS or al.startswith("dependabot"):
        return True, "dependabot"
    if draft and not review_drafts:
        return True, "draft"
    return False, ""


def action_review_argv(
    repo: str,
    number: int,
    *,
    dry_run: bool = False,
    execute_tests: bool = False,
) -> list[str]:
    """Default Action command: review --comment, never --execute-install."""
    argv = ["python", "-m", "cli.main", "review", repo, str(number)]
    if dry_run:
        argv.append("--dry-run")
    else:
        argv.append("--comment")
    if execute_tests:
        argv.append("--execute-tests")
    return argv
