"""Phase 5.1 — golden gate eval.

Usage:
    python -m tests.evaluation.run_eval --offline
    python -m tests.evaluation.run_eval --live --ids qw-538,qw-571
    python -m tests.evaluation.run_eval --live --profile execute --ids qw-538,qw-571
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from core.evaluation.snapshot import (
    SNAPSHOT_PATH,
    ReviewSnapshot,
    from_logs,
    load_snapshot,
)
from tests.evaluation.schema import GoldenCase, Scorecard
from tests.evaluation.scorer import score

EVAL_DIR = Path(__file__).resolve().parent
GOLDENS_DIR = EVAL_DIR / "goldens"
FIXTURES_DIR = EVAL_DIR / "fixtures"


def load_golden(path: Path) -> GoldenCase:
    return GoldenCase.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_goldens(ids: Optional[List[str]] = None) -> List[GoldenCase]:
    want = {i.strip() for i in (ids or []) if i.strip()}
    cases: List[GoldenCase] = []
    for p in sorted(GOLDENS_DIR.glob("*.json")):
        g = load_golden(p)
        if want and g.id not in want:
            continue
        cases.append(g)
    return cases


def fixture_for(case: GoldenCase) -> Path:
    return FIXTURES_DIR / f"{case.id}.snapshot.json"


def format_card(card: Scorecard) -> str:
    if card.ok:
        names = " ".join(card.passed_names)
        return f"{card.case_id}  PASS  {names}"
    fail = card.failed[0]
    return f"{card.case_id}  FAIL  {fail.name} {fail.detail}"


def run_offline(ids: Optional[List[str]] = None, profile: str = "gates") -> int:
    cases = list_goldens(ids)
    if not cases:
        print("no golden cases", file=sys.stderr)
        return 1
    rc = 0
    for g in cases:
        fx = fixture_for(g)
        if not fx.is_file():
            print(f"{g.id}  FAIL  missing fixture {fx}", file=sys.stderr)
            rc = 1
            continue
        snap = load_snapshot(fx)
        card = score(g, snap, profile=profile)
        print(format_card(card))
        if not card.ok:
            rc = 1
            for c in card.failed:
                print(f"  - {c.name}: {c.detail}")
    return rc


def _run_live_review(golden: GoldenCase, profile: str, timeout_s: int) -> ReviewSnapshot:
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "review",
        golden.repo,
        str(golden.number),
        "--dry-run",
        "-v",
    ]
    if profile == "execute":
        cmd.append("--execute-tests")
    env = os.environ.copy()
    env["CODETURTLE_EVAL"] = "1"
    # Never --execute-install in default eval.
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if SNAPSHOT_PATH.is_file():
        try:
            snap = load_snapshot(SNAPSHOT_PATH)
            if snap.repo and snap.number == golden.number:
                return snap
        except Exception:
            pass
    return from_logs(out, repo=golden.repo, number=golden.number)


def run_live(
    ids: Optional[List[str]] = None,
    profile: str = "gates",
    timeout_s: int = 600,
) -> int:
    cases = list_goldens(ids)
    if not cases:
        print("no golden cases", file=sys.stderr)
        return 1
    rc = 0
    for g in cases:
        try:
            snap = _run_live_review(g, profile, timeout_s)
        except subprocess.TimeoutExpired:
            print(f"{g.id}  FAIL  live review timeout")
            rc = 1
            continue
        except Exception as exc:
            print(f"{g.id}  FAIL  live review error {exc}")
            rc = 1
            continue
        card = score(g, snap, profile=profile)
        print(format_card(card))
        if not card.ok:
            rc = 1
            for c in card.failed:
                print(f"  - {c.name}: {c.detail}")
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Golden gate eval for PR review")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Score fixture snapshots (CI)")
    mode.add_argument("--live", action="store_true", help="Run real reviews then score")
    parser.add_argument("--ids", default="", help="Comma-separated golden ids")
    parser.add_argument(
        "--profile",
        default="gates",
        choices=("gates", "execute"),
        help="gates: default dry-run (no --execute-tests). execute: --execute-tests only, no install",
    )
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    ids = [x.strip() for x in (args.ids or "").split(",") if x.strip()] or None
    if args.live:
        return run_live(ids, profile=args.profile, timeout_s=args.timeout)
    return run_offline(ids, profile=args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
