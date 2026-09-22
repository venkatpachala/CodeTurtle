"""core/output/github_review.py — GitHub PR review comment adapter.

KEY INVARIANT:
  --dry-run means "don't POST to GitHub". It does NOT mean "don't generate comments."
  Dry-run still returns the full list of comment dicts that would have been posted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.review.finding import ReviewFinding


def publish_review(
    pr: Any,
    findings: "List[ReviewFinding]",
    *,
    dry_run: bool = True,
    decision: str = "COMMENT",
    summary: str = "",
    token: str = "",
) -> List[Dict[str, Any]]:
    """Build GitHub review comment dicts and optionally post them.

    Args:
        pr: PyGithub PullRequest object (only needed when dry_run=False).
        findings: List of ReviewFinding objects from the review pipeline.
        dry_run: If True, return comments without posting. Default True.
        decision: APPROVE | REQUEST_CHANGES | COMMENT
        summary: Top-level review body text.
        token: GitHub token (only needed when dry_run=False).

    Returns:
        List of comment dicts: [{"path": ..., "line": ..., "body": ...}, ...]
        Always returns the full list regardless of dry_run.
    """
    from core.review.finding import VERIFICATION_DISPROVED

    # GitHub receives only verified findings. Benchmark artifacts deliberately
    # retain every survivor, including uncertain findings, for diagnostics.
    postable = [f for f in findings if f.verification_status == "verified"]
    comments = [f.to_github_comment() for f in postable if f.file and f.line]

    if dry_run:
        return comments

    # Live posting path
    if pr is None:
        return comments

    try:
        _post_github_review(pr, comments, decision=decision, summary=summary)
    except Exception as exc:
        print(f"[GitHub] WARNING: failed to post review: {exc}")

    return comments


def _post_github_review(
    pr: Any,
    comments: List[Dict[str, Any]],
    *,
    decision: str,
    summary: str,
) -> None:
    """Post inline comments to a GitHub PR via PyGithub."""
    event_map = {
        "REQUEST_CHANGES": "REQUEST_CHANGES",
        "APPROVE": "APPROVE",
        "MERGE": "APPROVE",
        "COMMENT": "COMMENT",
    }
    event = event_map.get(decision.upper(), "COMMENT")

    # Build review comment objects
    review_comments = []
    for c in comments:
        path = c.get("path") or ""
        line = c.get("line")
        body = c.get("body") or ""
        if path and line and body:
            review_comments.append(
                pr.create_review_comment(
                    body=body,
                    commit=pr.get_commits().reversed[0],
                    path=path,
                    line=int(line),
                )
            )
    # Post the overall review
    if not review_comments:
        pr.create_review(body=summary or "CodeTurtle review complete.", event=event)
