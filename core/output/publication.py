"""Canonical preview and grouped GitHub delivery. No silent success paths."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from core.runtime.models import ReviewResult
from core.verification.diff_index import build_diff_index


@dataclass(frozen=True)
class PublicationPlan:
    repo: str
    number: int
    head_sha: str
    base_sha: str
    event: str
    body: str
    comments: list[dict] = field(default_factory=list)
    summary_only_findings: list[str] = field(default_factory=list)
    marker: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PublicationResult:
    status: str
    review_id: int | None = None
    url: str = ""
    error_code: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"published", "already_published", "dry_run"}

    def to_dict(self) -> dict:
        return asdict(self)


def build_publication_plan(result: ReviewResult, *, full_diff: str,
                           approve: bool = False, inline_max: int = 8) -> PublicationPlan:
    if result.decision is None or result.health.status in {"failed", "skipped"}:
        raise ValueError("analysis has no publishable verdict")
    if result.decision not in {"MERGE", "COMMENT", "REQUEST_CHANGES"}:
        raise ValueError("invalid decision")
    target = result.target
    if not target.repo or target.number <= 0 or not re.fullmatch(r"[0-9a-fA-F]{40}", target.head_sha):
        raise ValueError("publication requires repository, PR number, and exact HEAD SHA")
    if target.diff_sha256 != hashlib.sha256(full_diff.encode()).hexdigest():
        raise ValueError("publication diff differs from reviewed diff")
    event = "REQUEST_CHANGES" if result.decision == "REQUEST_CHANGES" else "COMMENT"
    if approve:
        if result.decision != "MERGE" or not result.approval_eligible:
            raise ValueError("approval is not eligible")
        event = "APPROVE"
    identity = hashlib.sha256(json.dumps([target.repo, target.number, target.head_sha, target.base_sha,
        event, sorted(f.fingerprint for f in result.product_findings)], sort_keys=True).encode()).hexdigest()
    marker = f"<!-- codeturtle-review-v2:{identity} -->"
    ratio = result.inspection.inspection_ratio
    ratio_text = "N/A" if ratio is None else f"{ratio:.0%}"
    lines = [marker, f"<!-- codeturtle-sha:{target.head_sha} -->", "", "## CodeTurtle review", "",
        f"**Recommendation:** {result.decision}", f"**Analysis:** {result.health.status}",
        f"**Inspection:** {result.inspection.inspected}/{result.inspection.eligible} ({ratio_text})",
        f"**Reasons:** {', '.join(result.policy_reasons or [result.policy_reason])}",
        "", "This is a review recommendation. No merge operation was performed.",
        "Tests are supporting evidence; this run does not establish BASE/HEAD regression attribution."]
    if result.unresolved:
        lines.extend(["", f"{len(result.unresolved)} unresolved investigation(s); human review required."])
    for stage in result.health.stages:
        if stage.status != "succeeded":
            lines.append(f"- {stage.stage}: {stage.status} ({stage.code})")
    index = build_diff_index(full_diff)
    comments, summary_only = [], []
    for finding in result.product_findings:
        lines.extend(["", f"### {finding.id}: {finding.title} ({finding.severity})",
                      f"`{finding.file}:{finding.line or '?'}`", finding.render_comment()])
        path = finding.file.replace("\\", "/")
        if (path in index.file_set() and finding.line and index.line_in_new_file(path, finding.line)
                and len(comments) < max(0, inline_max)):
            comment = finding.to_github_comment()
            comment["body"] += f"\n<!-- codeturtle-finding:{finding.fingerprint} -->"
            comments.append(comment)
        else:
            summary_only.append(finding.id)
    if not result.product_findings:
        lines.extend(["", "No substantiated defects found within the reported analysis scope."])
    body = "\n".join(lines)
    if len(body.encode()) > 60000:
        raise ValueError("review body exceeds publication budget; reduce review scope")
    return PublicationPlan(target.repo, target.number, target.head_sha, target.base_sha,
                           event, body, comments, summary_only, marker)


def _existing(pr: Any, plan: PublicationPlan, publisher_login: str) -> Any:
    for review in pr.get_reviews():
        if (review.user.login == publisher_login and review.commit_id == plan.head_sha
                and plan.marker in (review.body or "") and review.state != "PENDING"):
            return review
    return None


def deliver_review(pr: Any, plan: PublicationPlan, *, dry_run: bool = True,
                   publisher_login: str = "") -> PublicationResult:
    if dry_run:
        return PublicationResult(status="dry_run")
    if not publisher_login:
        return PublicationResult(status="failed", error_code="publisher_identity_missing")
    try:
        pr.update()
        if pr.number != plan.number or pr.base.repo.full_name.lower() != plan.repo.lower():
            return PublicationResult(status="failed", error_code="target_mismatch")
        if pr.head.sha != plan.head_sha or (plan.base_sha and pr.base.sha != plan.base_sha):
            return PublicationResult(status="stale", error_code="reviewed_revision_changed")
        existing = _existing(pr, plan, publisher_login)
        if existing:
            return PublicationResult("already_published", existing.id, existing.html_url)
        commit = pr.base.repo.get_commit(plan.head_sha)
        review = pr.create_review(commit=commit, body=plan.body, event=plan.event, comments=plan.comments)
        return PublicationResult("published", review.id, review.html_url)
    except Exception as exc:
        # Never blindly retry a mutation after an ambiguous response.
        try:
            existing = _existing(pr, plan, publisher_login)
            if existing:
                return PublicationResult("already_published", existing.id, existing.html_url)
        except Exception:
            pass
        return PublicationResult("failed", error_code="github_delivery_failed", error=type(exc).__name__)
