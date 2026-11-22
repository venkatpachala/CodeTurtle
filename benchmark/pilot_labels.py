"""Link published Martian issue references to frozen pilot cases and audited replay trees."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess

import httpx

from benchmark.pilot import load_inputs
from core.review.artifacts import write_json_atomic

PUBLISHER = "withmartian/code-review-benchmark"
REVISION = "23a35d0d64f7de5a68e5679da08414e0edacea9b"
FUNCTIONAL = {"bug", "concurrency", "data", "api", "security"}


def pull_path(url: str) -> str:
    fields = url.split("/")
    if len(fields) != 7 or fields[:3] != ["https:", "", "github.com"] or fields[5] != "pull" or not fields[6].isdigit():
        raise ValueError("invalid public PR URL")
    return f"/repos/{fields[3]}/{fields[4]}/pulls/{fields[6]}"


def comment_key(comment):
    return (comment.get("created_at"), comment.get("path"), (comment.get("body") or "").strip())


def import_labels(root: Path, output: Path):
    registry, cases = load_inputs(root)
    url = f"https://raw.githubusercontent.com/{PUBLISHER}/{REVISION}/offline/results/benchmark_data.json"
    published = httpx.get(url, timeout=90)
    published.raise_for_status()
    pool = published.json()
    token = subprocess.check_output(["gh","auth","token","--hostname","github.com"], text=True).strip()
    with httpx.Client(base_url="https://api.github.com", headers={"Authorization": "Bearer " + token},
                      follow_redirects=True, timeout=20) as api:
        def get(path):
            response = api.get(path)
            response.raise_for_status()
            return response.json()

        @lru_cache(maxsize=512)
        def tree(repository, revision):
            obj = get(f"{repository}/git/commits/{revision}")
            if obj["sha"] != revision:
                raise ValueError("commit response identity mismatch")
            return obj["tree"]["sha"]

        def check_replay(review, original_trees):
            path = pull_path(review["pr_url"])
            repository = path.split("/pulls/")[0]
            keys = {comment_key(c) for c in review["review_comments"] if c.get("path") and c.get("body")}
            comments = get(path + "/comments?per_page=100")
            revisions = {c["original_commit_id"] for c in comments if comment_key(c) in keys and c.get("original_commit_id")}
            if not revisions:
                return {"pr_url": review["pr_url"], "status":"no_archived_inline_comment_anchor"}
            pr = get(path)
            for revision in sorted(revisions):
                if tree(repository, revision) != original_trees["head"]:
                    continue
                compare = get(f"{repository}/compare/{pr['base']['sha']}...{revision}?per_page=1")
                base = compare["merge_base_commit"]["sha"]
                if tree(repository, base) == original_trees["base"]:
                    return {"pr_url":review["pr_url"], "status":"exact_base_and_head_trees",
                            "reviewed_commit":revision, "comparison_base":base, "trees":original_trees}
            return {"pr_url":review["pr_url"], "status":"revision_trees_differ", "reviewed_commits":sorted(revisions)}

        def annotate(case):
            url = case["pr_url"]
            entry = pool.get(url)
            result = {"pr_url":url, "case_id":case["case_id"], "split":case["split"],
                      "base_sha":case["base_sha"], "head_sha":case["head_sha"], "issue_labels":[],
                      "exposure_audit":"pending","status":"pending","truth":None,"replica_checks":[]}
            if entry is None:
                # Approval at this SHA is useful context, but cannot establish bug absence.
                try:
                    reviews = get(pull_path(url) + "/reviews?per_page=100")
                    result["approved_reviews_at_head_first_page"] = sum(
                        r["state"] == "APPROVED" and r.get("commit_id") == case["head_sha"] for r in reviews)
                except httpx.HTTPError:
                    result["approved_reviews_at_head_first_page"] = None
                result["reference_status"] = "no_published_case_match"
                return result
            refs = entry["golden_comments"]
            result["source_document"] = f"https://github.com/{PUBLISHER}/blob/{REVISION}/offline/golden_comments/{entry['golden_source_file']}"
            result["issue_labels"] = [{"ordinal":i, "category":c["category"], "severity":c["severity"],
                                       "comment_sha256":hashlib.sha256(c["comment"].encode()).hexdigest()}
                                      for i,c in enumerate(refs)]
            result["reference_status"] = "pr_url_only"
            repo = pull_path(url).split("/pulls/")[0]
            try:
                original = {"base":tree(repo, case["comparison_base_sha"]), "head":tree(repo, case["head_sha"])}
                replays = [r for r in entry["reviews"] if r["review_comments"] and r.get("pr_url")]
                # Prefer archived reviews on the target itself, then two distinct replay PRs.
                # Combine anchors from tools reviewing the same revision.
                by_url = {}
                for review in sorted(replays, key=lambda r: r["pr_url"] != url):
                    by_url.setdefault(review["pr_url"], []).extend(review["review_comments"])
                for replay_url, comments in list(by_url.items())[:3]:
                    try:
                        audit = check_replay({"pr_url":replay_url,"review_comments":comments}, original)
                    except (httpx.HTTPError, ValueError, KeyError) as exc:
                        audit = {"pr_url":replay_url, "status":"unavailable", "error_type":type(exc).__name__}
                    result["replica_checks"].append(audit)
                    if audit["status"] == "exact_base_and_head_trees":
                        result["reference_status"] = audit["status"]
                        if any(c["category"] in FUNCTIONAL for c in refs):
                            result.update(status="adjudicated", truth={
                                "label":"defective", "base_sha":case["base_sha"], "head_sha":case["head_sha"],
                                "labelers":["Martian offline benchmark published human-verified references (individual identities unspecified)"],
                                "evidence":[result["source_document"],audit["pr_url"],f"Git trees BASE {original['base']} HEAD {original['head']}"],
                                "rationale":"At least one published functional issue, with both Git trees matching an archived benchmark review. External reference label; independent CodeTurtle adjudication pending."})
                        break
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                result["audit_error"] = type(exc).__name__
            return result

        with ThreadPoolExecutor(max_workers=3) as workers:
            annotations = {row["pr_url"]:row for row in workers.map(annotate,cases)}
    output.mkdir(parents=True,exist_ok=False)
    write_json_atomic(output/"annotations.json",annotations)
    report = {"source":url,"publisher_revision":REVISION,"source_sha256":hashlib.sha256(published.content).hexdigest(),
              "inputs_sha256":registry["inputs_sha256"],"reference_status":dict(Counter(r["reference_status"] for r in annotations.values())),
              "published_issue_count":sum(len(r["issue_labels"]) for r in annotations.values()),
              "externally_labeled_defective":sum(r["truth"] is not None for r in annotations.values()),
              "scope":"Source attribution and replay-tree comparison. Categories are publisher annotations. Controls without matched reference remain unlabeled."}
    write_json_atomic(output/"report.json",report)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    import_labels(args.root,args.output)
