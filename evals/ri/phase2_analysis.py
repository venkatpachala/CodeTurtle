"""Phase 2: PR analysis vs real diff facts."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.ri.fixtures import fetch_pr, save, load
from evals.ri.report import PhaseReport
from core.pr_analysis import pr_analysis_agent  # adjust import


def evaluate(repo: str, number: int) -> PhaseReport:
    state = fetch_pr(repo, number)
    # optional: attach understanding from phase1
    try:
        u = load(repo, number, "01_understanding.json")
        state["pr_understanding"] = u.get("output") or {}
    except FileNotFoundError:
        pass

    out = pr_analysis_agent(state)
    analysis = out.get("pr_analysis") or {}
    save(repo, number, "02_analysis.json", {"output": analysis, "raw": out})

    gh_files = set(state["files_changed"])
    reported = set(analysis.get("changed_files") or analysis.get("files_changed") or [])
    r = PhaseReport("Phase2 PR Analysis")
    r.add(
        "files_match_github",
        reported == gh_files or reported.issubset(gh_files) and len(reported) > 0,
        f"gh={sorted(gh_files)} reported={sorted(reported)}",
    )
    tests_paths = any("test" in f.lower() for f in gh_files)
    flag = bool(analysis.get("tests_added_or_modified"))
    # soft: if tests in paths, flag should ideally be true
    r.add(
        "tests_flag_consistent",
        (not tests_paths) or flag,
        f"tests_in_paths={tests_paths} flag={flag}",
    )
    added = set(analysis.get("added_functions") or [])
    modified = set(analysis.get("modified_functions") or [])
    r.add(
        "no_func_in_both_added_and_modified",
        len(added & modified) == 0,
        f"overlap={added & modified}",
    )
    r.print()
    return r


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "Graphify-Labs/graphify"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    evaluate(repo, number)