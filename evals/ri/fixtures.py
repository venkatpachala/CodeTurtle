"""Load real PR context. No fake diffs."""
from __future__ import annotations

import json
import os
from pathlib import Path

from github import Github

from config import settings

OUTPUT_ROOT = Path("evals/outputs")


def out_dir(repo: str, number: int) -> Path:
    d = OUTPUT_ROOT / f"{repo.replace('/', '_')}_{number}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(repo: str, number: int, name: str, data: dict) -> Path:
    p = out_dir(repo, number) / name
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return p


def load(repo: str, number: int, name: str) -> dict:
    p = out_dir(repo, number) / name
    if not p.exists():
        raise FileNotFoundError(
            f"Missing {p}. Run earlier phase first."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def fetch_pr(repo: str, number: int) -> dict:
    """Real GitHub PR → dict used as ReviewState seed."""
    g = Github(settings.github_token)
    pr = g.get_repo(repo).get_pull(number)
    files = list(pr.get_files())
    parts = []
    for f in files:
        if f.patch:
            parts.append(f"--- {f.filename}\n+++ {f.filename}\n{f.patch}\n")
    return {
        "repo": repo,
        "number": number,
        "title": pr.title,
        "body": pr.body or "",
        "author": pr.user.login,
        "files_changed": [f.filename for f in files],
        "full_diff": "\n".join(parts),
    }


def seed_state(repo: str, number: int) -> dict:
    base = fetch_pr(repo, number)
    # Optional: attach kb/engine only for retrieval phase
    return base