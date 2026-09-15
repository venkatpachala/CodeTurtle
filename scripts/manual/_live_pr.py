"""
Shared helper: fetch a REAL PR from GitHub — identical logic to
cli/commands/review.py's ReviewPipeline._fetch_pr / _build_full_diff, just
inlined here so every numbered stage script can call it directly. This is a
live network call using your GITHUB_TOKEN (from .env / config.settings). No
mocking, no fixture fallback — if this fails, it fails loudly rather than
silently handing you fabricated PR content.
"""

from config import settings
from github import Github


def fetch_live_pr(repo: str, number: int) -> dict:
    if not settings.github_token:
        print("WARNING: settings.github_token is empty (no GITHUB_TOKEN in your "
              ".env). GitHub's API will likely rate-limit or reject this fetch.")

    print(f"Fetching real PR data: {repo}#{number} ...")
    g = Github(settings.github_token) if settings.github_token else Github()
    repo_obj = g.get_repo(repo)
    pr = repo_obj.get_pull(number)

    files = list(pr.get_files())
    files_changed = [f.filename for f in files]
    full_diff = ""
    skipped_files = []
    for f in files:
        if f.patch:
            full_diff += f"--- {f.filename}\n+++ {f.filename}\n{f.patch}\n\n"
        else:
            # GitHub returns no .patch for binary files or diffs too large to
            # render inline — real API behavior, not something hidden here.
            skipped_files.append(f.filename)

    print(f"Real PR title   : {pr.title}")
    print(f"Real PR author  : {pr.user.login}")
    print(f"Files changed   : {len(files_changed)}")
    if skipped_files:
        print(f"Files with NO diff from GitHub (binary/too large): {skipped_files}")
    print(f"full_diff length: {len(full_diff)} chars")

    return {
        "repo": repo,
        "number": number,
        "title": pr.title,
        "body": pr.body or "",
        "author": pr.user.login,
        "files_changed": files_changed,
        "full_diff": full_diff,
    }
