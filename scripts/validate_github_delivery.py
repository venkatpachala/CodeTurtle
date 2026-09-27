"""Real GitHub duplicate/stale/target checks using a saved authorized review plan.

Never invents findings or changes the plan's decision. Requires the user's
authorization to publish on the target PR before invoking this script.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import re
from dataclasses import replace
from pathlib import Path
from github import Github, Auth
from core.ci import github_authentication, resolve_github_token
from core.output.publication import PublicationPlan, deliver_review
from core.review.artifacts import write_json_atomic


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prediction", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise-inline", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.prediction.read_text(encoding="utf-8"))
    if not data.get("publication_preview"):
        raise ValueError("prediction contains no publication plan")
    plan = PublicationPlan(**data["publication_preview"])
    with github_authentication("gh"):
        client = Github(auth=Auth.Token(resolve_github_token()), timeout=30, retry=2)
        login = client.get_user().login
        pr = client.get_repo(plan.repo).get_pull(plan.number)
        before = len(list(pr.get_reviews()))
        duplicate = deliver_review(pr, plan, dry_run=False, publisher_login=login)
        after = len(list(pr.get_reviews()))
        stale = deliver_review(pr, replace(plan, head_sha="0" * 40), dry_run=False, publisher_login=login)
        wrong_target = deliver_review(pr, replace(plan, number=plan.number + 1), dry_run=False, publisher_login=login)
        report = {"duplicate": duplicate.to_dict(), "reviews_before": before, "reviews_after": after,
                  "stale": stale.to_dict(), "wrong_target": wrong_target.to_dict()}
        inline_passed = True
        if args.exercise_inline:
            comment = None
            for changed in pr.get_files():
                for line in (changed.patch or "").splitlines():
                    match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
                    if match and int(match.group(1)) > 0 and int(match.group(2) or 1) > 0:
                        comment = {"path": changed.filename, "line": int(match.group(1)), "side": "RIGHT",
                            "body": "CodeTurtle delivery validation: this is a test annotation, not a defect claim. "
                                    "The summary and this inline were submitted together in one review."}
                        break
                if comment:
                    break
            if not comment:
                raise ValueError("PR has no right-side diff line for an inline delivery test")
            identity = hashlib.sha256((plan.head_sha + "inline-delivery-v1").encode()).hexdigest()
            marker = f"<!-- codeturtle-review-v2:{identity} -->"
            inline_plan = replace(plan, event="COMMENT", marker=marker, comments=[comment],
                body=marker + "\nCodeTurtle integration test: grouped summary and inline delivery. No defect is asserted.")
            inline = deliver_review(pr, inline_plan, dry_run=False, publisher_login=login)
            inline_duplicate = deliver_review(pr, inline_plan, dry_run=False, publisher_login=login)
            report.update(inline_delivery=inline.to_dict(), inline_duplicate=inline_duplicate.to_dict())
            inline_passed = inline.ok and inline_duplicate.status == "already_published"
        write_json_atomic(args.output, report)
        passed = (duplicate.status == "already_published" and before == after
                  and stale.status == "stale" and wrong_target.error_code == "target_mismatch" and inline_passed)
        print("PASS" if passed else "FAIL")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
