"""Capture a real PR diff with immutable revision metadata, without loading gold."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from github import Auth, Github
from benchmark.frozen import FrozenCase
from core.ci import github_authentication, resolve_github_token
from core.review.artifacts import write_json_atomic


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("number", type=int)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--lineage-id", required=True)
    parser.add_argument("--split", choices=["development", "validation", "test"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-auth", choices=["configured", "gh", "anonymous"], default="configured")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError("frozen inputs cannot overwrite an existing capture")
    with github_authentication(args.github_auth):
        token = resolve_github_token()
        client = Github(auth=Auth.Token(token) if token else None, timeout=30, retry=2)
        pr = client.get_repo(args.repo).get_pull(args.number)
        base, head = pr.base.sha, pr.head.sha
        parts = []
        for changed in pr.get_files():
            if not changed.patch:
                raise ValueError("cannot freeze a complete patch: GitHub omitted a file patch")
            name = changed.filename
            previous = changed.previous_filename or name
            parts.append(f"diff --git a/{previous} b/{name}")
            if changed.status == "added":
                parts.extend(["--- /dev/null", f"+++ b/{name}"])
            elif changed.status in {"removed", "deleted"}:
                parts.extend([f"--- a/{previous}", "+++ /dev/null"])
            else:
                parts.extend([f"--- a/{previous}", f"+++ b/{name}"])
            parts.extend([changed.patch, ""])
        diff = "\n".join(parts)
        pr.update()
        if pr.head.sha != head or pr.base.sha != base:
            raise ValueError("PR changed during input capture")
        case = FrozenCase(case_id=args.case_id, repo=args.repo, number=args.number, base_sha=base,
            head_sha=head, diff_file="input.diff", diff_sha256=hashlib.sha256(diff.encode()).hexdigest(),
            lineage_id=args.lineage_id, split=args.split)
        args.output_dir.mkdir(parents=True)
        (args.output_dir / "input.diff").write_bytes(diff.encode())
        write_json_atomic(args.output_dir / "manifest.json", [case.model_dump()])
    print(f"Frozen input captured at {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
