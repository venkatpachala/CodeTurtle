"""Phase 6.1/6.2 — post one GitHub PR review (summary + optional inlines)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from core.ignore import is_ignored
from core.pr_facts import _is_docs_or_trivia, is_lockfile, normalize_path
from core.verification.diff_index import DiffIndex, build_diff_index
from core.verification.policy import (
    clamp_recommendation,
    recommendation_from_verification,
)

MARKER = "<!-- codeturtle-review -->"
SHA_PREFIX = "<!-- codeturtle-sha:"


_SEV_RANK = {
    "critical": 0,
    "blocking": 1,
    "high": 2,
    "medium": 3,
    "concern": 4,
    "suggestion": 5,
    "question": 6,
    "nit": 7,
    "low": 8,
}


@dataclass
class PostResult:
    attempted: bool = False
    ok: bool = False
    skipped: bool = False
    skip_reason: str = ""
    event: str = ""
    decision: str = ""
    body: str = ""
    url: str = ""
    pr_url: str = ""
    error: str = ""
    inlines: int = 0
    skipped_inline: int = 0
    comments: List[dict] = field(default_factory=list)


def should_post(*, dry_run: bool, comment: bool) -> bool:
    """Default dry-run is no post. --comment or --no-dry-run posts."""
    if comment:
        return True
    return not dry_run


def github_event(decision: str, classification: str = "") -> str:
    """Map clamped recommendation to a GitHub review event."""
    rec = str(decision or "COMMENT").upper()
    if classification == "lockfile-only":
        return "COMMENT"
    if rec == "REQUEST_CHANGES":
        return "REQUEST_CHANGES"
    if rec == "MERGE":
        return "APPROVE"
    return "COMMENT"


def clamped_decision(state: dict) -> str:
    facts = state.get("pr_facts") or {}
    classification = str(facts.get("classification") or "")
    findings = list(state.get("validated_findings") or state.get("findings") or [])
    vrep = state.get("verification_report") if isinstance(state.get("verification_report"), dict) else {}
    exrep = state.get("execution_report") if isinstance(state.get("execution_report"), dict) else {}
    understanding = state.get("pr_understanding") or {}
    risk = ""
    if isinstance(understanding, dict):
        risk = str(understanding.get("risk_level") or "")
    baseline = recommendation_from_verification(
        findings,
        classification=classification,
        risk=risk or "medium",
        execution=exrep or None,
    )
    rec = str(state.get("recommendation") or vrep.get("suggested_recommendation") or baseline)
    return clamp_recommendation(rec, baseline, classification)


def is_postable_finding(finding: Dict[str, Any] | None) -> bool:
    d = finding or {}
    fp = normalize_path(str(d.get("file") or d.get("path") or ""))
    if not fp:
        return False
    if _is_docs_or_trivia(fp):
        return False
    return True


def keep_findings_for_body(state: dict) -> List[dict]:
    findings = list(state.get("validated_findings") or state.get("findings") or [])
    out: List[dict] = []
    for f in findings:
        d = f if isinstance(f, dict) else {}
        if is_postable_finding(d):
            out.append(d)
    return out


def inline_comment_body(finding: dict) -> str:
    title = str(finding.get("title") or finding.get("claim") or "finding").strip()
    sev = str(finding.get("severity") or "?")
    st = str(finding.get("verification_status") or "supported")
    claim = str(
        finding.get("claim")
        or finding.get("reasoning")
        or finding.get("description")
        or ""
    ).strip()
    if len(claim) > 400:
        claim = claim[:397] + "..."
    fp = normalize_path(str(finding.get("file") or ""))
    lines = [f"**{title}** ({sev}, {st})"]
    if claim:
        lines.extend(["", claim])
    if fp:
        lines.extend(["", f"File: `{fp}`"])
    return "\n".join(lines).rstrip() + "\n"


def _files_in_pr(state: dict, index: DiffIndex) -> set[str]:
    facts = state.get("pr_facts") or {}
    paths = list(facts.get("files_changed") or state.get("files_changed") or [])
    out = {normalize_path(p).lower() for p in paths if p}
    for p in index.file_set():
        out.add(normalize_path(p).lower())
    return out


def _path_in_pr(path: str, allowed: set[str], index: DiffIndex) -> bool:
    n = normalize_path(path).lower()
    if not n:
        return False
    if n in allowed or n.split("/")[-1] in {a.split("/")[-1] for a in allowed}:
        return True
    return index.has_file(path)


def build_inline_comments(
    state: dict,
    *,
    index: Optional[DiffIndex] = None,
    inline_max: Optional[int] = None,
    inline_lockfile: Optional[bool] = None,
) -> Tuple[List[dict], int]:
    """KEEP ∩ supported ∩ resolvable RIGHT line. Cap inline_max. No lockfile-only."""
    facts = state.get("pr_facts") or {}
    classification = str(facts.get("classification") or "")
    if inline_lockfile is None:
        if state.get("inline_lockfile") is not None:
            inline_lockfile = bool(state.get("inline_lockfile"))
        else:
            inline_lockfile = bool(getattr(settings, "inline_lockfile", False))
    allow_lock = bool(inline_lockfile)
    if classification == "lockfile-only" and not allow_lock:
        return [], 0
    if inline_max is None and state.get("inline_max") is not None:
        inline_max = state.get("inline_max")
    cap = int(
        inline_max
        if inline_max is not None
        else getattr(settings, "inline_max", 8)
    )
    idx = index or build_diff_index(state.get("full_diff") or "")
    allowed = _files_in_pr(state, idx)
    findings = list(state.get("validated_findings") or state.get("findings") or [])
    candidates: List[tuple[int, int, dict, int]] = []
    skipped = 0
    for i, f in enumerate(findings):
        d = f if isinstance(f, dict) else {}
        if not is_postable_finding(d):
            continue
        if str(d.get("verification_status") or "") != "supported":
            continue
        fp = normalize_path(str(d.get("file") or ""))
        ignore = list(state.get("ignore_paths") or [])
        if is_ignored(fp, ignore):
            skipped += 1
            print(f"[GitHub] inline skip file={fp} reason=ignored")
            continue
        if is_lockfile(fp) and not allow_lock:
            skipped += 1
            print(f"[GitHub] inline skip file={fp} reason=lockfile")
            continue
        if not _path_in_pr(fp, allowed, idx):
            skipped += 1
            print(f"[GitHub] inline skip file={fp} reason=not_in_diff")
            continue
        line = idx.line_for_finding(
            fp,
            start_line=d.get("start_line"),
            hunk_header=str(d.get("hunk_header") or ""),
            tokens=list(d.get("matched_tokens") or []),
        )
        if not line:
            skipped += 1
            print(f"[GitHub] inline skip file={fp} reason=no_line")
            continue
        sev = str(d.get("severity") or "").lower()
        rank = _SEV_RANK.get(sev, 50)
        candidates.append((rank, i, d, int(line)))

    candidates.sort(key=lambda t: (t[0], t[1]))
    chosen = candidates[: max(0, cap)]
    if len(candidates) > cap:
        skipped += len(candidates) - cap
    comments: List[dict] = []
    for _rank, _i, d, line in chosen:
        fp = normalize_path(str(d.get("file") or ""))
        resolved = idx._resolve(fp) or fp
        comments.append(
            {
                "path": resolved,
                "line": line,
                "side": "RIGHT",
                "body": inline_comment_body(d),
            }
        )
        print(
            f"[GitHub] inline file={resolved} line={line} "
            f"status={d.get('verification_status')}"
        )
    return comments, skipped


def _claim(f: dict) -> str:
    text = str(
        f.get("claim")
        or f.get("title")
        or f.get("description")
        or f.get("reasoning")
        or ""
    ).strip()
    if len(text) > 240:
        text = text[:237] + "..."
    return text


def build_review_body(state: dict, *, sha: str = "", decision: str = "") -> str:
    facts = state.get("pr_facts") or {}
    classification = str(facts.get("classification") or "")
    rec = decision or clamped_decision(state)
    understanding = state.get("pr_understanding") or {}
    summary = ""
    if isinstance(understanding, dict):
        summary = str(understanding.get("summary") or "").strip()
    kept = keep_findings_for_body(state)
    val = state.get("validation_report") if isinstance(state.get("validation_report"), dict) else {}
    dropped_n = int(val.get("dropped") or 0)
    lines = [MARKER]
    if sha:
        lines.append(f"{SHA_PREFIX}{sha} -->")
    lines.extend(["", "## CodeTurtle review", "", f"**Decision:** {rec}", ""])
    if summary:
        lines.extend([summary, ""])
    if classification == "lockfile-only" and not kept:
        lines.extend(
            [
                "No grounded issues; lockfile-only.",
                "",
            ]
        )
    elif kept:
        lines.append("### Findings (KEEP)")
        lines.append("")
        for f in kept:
            fp = normalize_path(str(f.get("file") or ""))
            sev = str(f.get("severity") or "?")
            st = str(f.get("verification_status") or "uncertain")
            lines.append(f"- `{fp}` — {sev} · {st}")
            claim = _claim(f)
            if claim:
                lines.append(f"  {claim}")
        lines.append("")
    else:
        lines.extend(["No validated findings.", ""])
    lines.extend(
        [
            "### Grounding",
            "",
            f"Kept {len(kept)} · dropped {dropped_n} (not listed as issues).",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def already_posted(reviews: list, *, sha: str, marker: str = MARKER) -> bool:
    """Skip if this bot already posted a review for the same head SHA."""
    if not sha:
        return False
    needle = f"{SHA_PREFIX}{sha}"
    for rev in reviews or []:
        body = ""
        if isinstance(rev, dict):
            body = str(rev.get("body") or "")
        else:
            body = str(getattr(rev, "body", "") or "")
        if marker in body and needle in body:
            return True
    return False


def _reviews_newest_first(pr: Any) -> list:
    try:
        revs = list(pr.get_reviews())
    except Exception:
        return []
    return list(reversed(revs))


def _looks_like_line_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    if "422" in s:
        return True
    return "line" in s and any(
        k in s for k in ("diff", "invalid", "not part", "pull request review", "path")
    )


def _drop_bad_inline(comments: List[dict], exc: BaseException) -> List[dict]:
    if not comments:
        return comments
    text = str(exc)
    remaining = comments
    for c in comments:
        path = str(c.get("path") or "")
        if path and path in text:
            remaining = [x for x in comments if x.get("path") != path]
            break
    if remaining is comments or len(remaining) == len(comments):
        remaining = comments[:-1]
    return remaining


def post_pull_request_review(
    pr: Any,
    state: dict,
    *,
    sha: str = "",
    create_review=None,
) -> PostResult:
    """Create one review: summary + optional KEEP/supported inlines."""
    facts = state.get("pr_facts") or {}
    classification = str(facts.get("classification") or "")
    decision = clamped_decision(state)
    event = github_event(decision, classification)
    body = build_review_body(state, sha=sha, decision=decision)
    pr_url = str(getattr(pr, "html_url", "") or "")
    comments, skipped_inline = build_inline_comments(state)
    result = PostResult(
        attempted=True,
        decision=decision,
        event=event,
        body=body,
        pr_url=pr_url,
        inlines=len(comments),
        skipped_inline=skipped_inline,
        comments=list(comments),
    )

    reviews = _reviews_newest_first(pr)
    if already_posted(reviews, sha=sha):
        result.skipped = True
        result.ok = True
        result.skip_reason = f"already posted for sha {sha}"
        result.inlines = 0
        result.comments = []
        return result

    fn = create_review or getattr(pr, "create_review", None)
    if fn is None:
        result.error = "create_review missing"
        return result

    commit = None
    if sha:
        try:
            repo = getattr(pr, "base", None)
            repo_obj = getattr(repo, "repo", None) if repo is not None else None
            if repo_obj is None:
                repo_obj = getattr(pr, "repo", None)
            if repo_obj is not None and hasattr(repo_obj, "get_commit"):
                commit = repo_obj.get_commit(sha)
        except Exception:
            commit = None
        if commit is None:
            head = getattr(pr, "head", None)
            commit = sha if head is not None else sha

    def _call(comms: List[dict]):
        kwargs: Dict[str, Any] = {"body": body, "event": event}
        if commit is not None:
            kwargs["commit"] = commit
        if comms:
            kwargs["comments"] = comms
        return fn(**kwargs)

    remaining = list(comments)
    dropped_api = 0
    review = None
    last_exc: Optional[BaseException] = None
    while True:
        try:
            review = _call(remaining)
            last_exc = None
            break
        except TypeError:
            try:
                kwargs2: Dict[str, Any] = {"body": body, "event": event}
                if remaining:
                    kwargs2["comments"] = remaining
                review = fn(**kwargs2)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
        except Exception as exc:
            last_exc = exc
        if remaining and last_exc is not None and _looks_like_line_error(last_exc):
            remaining = _drop_bad_inline(remaining, last_exc)
            dropped_api += 1
            print(
                f"[GitHub] inlines_dropped=api remaining={len(remaining)}"
            )
            continue
        break

    if review is None:
        result.error = str(last_exc or "create_review failed")
        result.inlines = 0
        return result

    result.ok = True
    result.inlines = len(remaining)
    result.skipped_inline = skipped_inline + dropped_api
    result.comments = remaining
    result.url = str(getattr(review, "html_url", "") or "")
    return result
