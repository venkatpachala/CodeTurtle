"""Sequential real-review ablations on frozen development cases, never held-out tuning."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from benchmark.frozen import FrozenCase, verify_case, validate_partitions
from core.review.artifacts import write_json_atomic

PROFILES = {
    "diff_only": {"GRAPHIFY_ENABLED": "false", "RULES_ENABLED": "false", "VERIFICATION_ENABLED": "true"},
    "graph": {"GRAPHIFY_ENABLED": "true", "RULES_ENABLED": "false", "VERIFICATION_ENABLED": "true"},
    "graph_rules": {"GRAPHIFY_ENABLED": "true", "RULES_ENABLED": "true", "VERIFICATION_ENABLED": "true"},
    "graph_rules_no_verification": {"GRAPHIFY_ENABLED": "true", "RULES_ENABLED": "true", "VERIFICATION_ENABLED": "false"},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    cases = [FrozenCase.model_validate(c) for c in json.loads(args.manifest.read_text(encoding="utf-8"))]
    validate_partitions(cases)
    if any(c.split != "development" for c in cases):
        raise ValueError("ablations are development-only; do not tune on held-out data")
    if args.output_dir.exists():
        raise FileExistsError("ablation outputs cannot overwrite an existing run")
    args.output_dir.mkdir(parents=True)
    records = []
    for case in cases:
        verify_case(case, args.manifest.parent)
        for profile, changes in PROFILES.items():
            path = args.output_dir / f"{case.case_id}-{profile}.json"
            if not path.resolve().is_relative_to(args.output_dir.resolve()):
                raise ValueError("invalid case identity")
            env = {**os.environ, **changes, "OLLAMA_MODEL": args.model, "LLM_BACKEND": "ollama"}
            command = [sys.executable, "-m", "cli.main", "review", case.repo, str(case.number), "--dry-run",
                       "--expected-head-sha", case.head_sha, "--expected-base-sha", case.base_sha,
                       "--json-output", str(path.resolve())]
            completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=args.timeout)
            prediction = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            actual_diff = ((prediction.get("result") or {}).get("target") or {}).get("diff_sha256")
            record = {"case_id": case.case_id, "profile": profile, "exit_code": completed.returncode,
                      "input_integrity": actual_diff == case.diff_sha256,
                      "result_path": path.name, "model": args.model, "options": changes}
            records.append(record)
            write_json_atomic(args.output_dir / "manifest.json", records)
    return 0 if all(r["exit_code"] == 0 and r["input_integrity"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
