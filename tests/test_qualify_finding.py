"""v0.4 qualify_finding + snippet line. Synthetic paths only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.positioner import line_for_finding, position_candidate
from core.runtime.models import Candidate
from core.runtime.qualify import NOT_A_DEFECT, PLAUSIBLE_BUT_UNPROVEN, qualify_finding
from core.runtime.verify_loop import verify_candidates
from core.verification.diff_index import build_diff_index
from core.verification.policy import decide

LOADER = "pkg/api/loader.py"


def _cand(**kwargs) -> Candidate:
    base = dict(
        bundle_id="B-001",
        file=LOADER,
        symbol="validate_selection",
        start_line=5,
        title="empty source_job_id accepted",
        claim="empty source_job_id accepted",
        existing_code="def validate_selection(source_job_id=None, source_trial_ids=None):",
        invariant="a source selector is required",
        violating_condition="both fields empty",
        execution_path=["validate_selection", "submit"],
        evidence=[LOADER],
        kind="defect",
        severity="medium",
        confidence=0.8,
    )
    base.update(kwargs)
    return Candidate(**base)


class TestQualifyFinding(unittest.TestCase):
    def test_xor_raise_is_not_a_defect(self):
        cand = _cand(
            title="Inconsistent task path and reference handling",
            claim="Exactly one of task_path or task_ref should be provided",
            existing_code=(
                "if (task_path is None) == (task_ref is None):\n"
                '    raise ValueError("Provide exactly one of -p/--task-path or -t/--task.")'
            ),
            invariant="Exactly one of task_path or task_ref should be provided",
            violating_condition="both or neither",
        )
        q = qualify_finding(cand)
        self.assertEqual(q.status, NOT_A_DEFECT)

    def test_error_print_is_not_a_defect(self):
        cand = _cand(
            title="Missing error handling for missing verifier sources",
            claim="regrade should handle missing verifier sources",
            existing_code='console.print("Error: Provide at least one verifier source via ")',
            invariant="regrade should handle the case where no verifier sources are provided",
        )
        q = qualify_finding(cand)
        self.assertEqual(q.status, NOT_A_DEFECT)

    def test_guard_removed_no_consumer_not_posted(self):
        cand = _cand(
            title="Potential missing guard for task_configs",
            claim="removing the empty guard might be dangerous",
            existing_code="if not task_configs:",
            invariant="task_configs should not be empty",
            violating_condition="empty task_configs",
            execution_path=["resolve_task_configs"],
            confidence=0.7,
        )
        q = qualify_finding(cand)
        self.assertEqual(q.status, PLAUSIBLE_BUT_UNPROVEN)
        rec, _ = decide(
            [
                {
                    "file": LOADER,
                    "title": cand.title,
                    "claim": cand.claim,
                    "severity": "nit",
                    "kind": "defect",
                    "verify_status": "uncertain",
                    "confidence": 0.7,
                }
            ],
            classification="source",
            files_changed=[LOADER],
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")

    def test_n_trials_with_consumer_can_verify(self):
        cand = _cand(
            title="Incorrect calculation of n_trials",
            claim="n_trials is submitted with a stale count",
            existing_code="n_trials = len(launch_config.tasks) * len(config.agents)",
            invariant="regrade trial count must equal source trial count",
            violating_condition="regrade present but n_trials from tasks",
            execution_path=["hosted_jobs.run", "submit"],
        )
        q = qualify_finding(cand)
        self.assertEqual(q.status, PLAUSIBLE_BUT_UNPROVEN)
        self.assertEqual(q.reason, "plausible")

    def test_n_trials_display_only_not_posted(self):
        cand = _cand(
            title="Incorrect calculation of n_trials",
            claim="n_trials is only used for the dry-run display summary",
            existing_code="n_trials = len(launch_config.tasks)",
            invariant="trial count for display",
            violating_condition="",
            execution_path=["format_summary"],
            confidence=0.7,
        )
        q = qualify_finding(cand)
        self.assertEqual(q.status, PLAUSIBLE_BUT_UNPROVEN)
        self.assertNotEqual(q.reason, "plausible")


class TestSnippetLine(unittest.TestCase):
    def test_snippet_at_148_not_cu_start_5(self):
        diff = (
            f"diff --git a/{LOADER} b/{LOADER}\n"
            f"--- a/{LOADER}\n"
            f"+++ b/{LOADER}\n"
            f"@@ -1,2 +5,4 @@\n"
            f" import os\n"
            f"+from x import y\n"
            f"@@ -140,2 +148,5 @@\n"
            f"+n_trials = len(launch_config.tasks) * len(config.agents)\n"
            f"+return n_trials\n"
            f" context\n"
        )
        idx = build_diff_index(diff)
        line = line_for_finding(
            idx, LOADER, "n_trials = len(launch_config.tasks) * len(config.agents)"
        )
        self.assertEqual(int(line), 148)
        pos = position_candidate(
            _cand(
                start_line=5,
                existing_code="n_trials = len(launch_config.tasks) * len(config.agents)",
            ),
            idx,
        )
        self.assertEqual(int(pos), 148)
        self.assertNotEqual(int(pos), 5)


class TestHarborShapedObservations(unittest.TestCase):
    def test_harbor_shaped_zero_posted(self):
        jobs = "pkg/cli/jobs.py"
        trials = "pkg/cli/trials.py"
        snippet_err = (
            "if not task_paths and not task_refs and not dataset_specs:\n"
            '    console.print(\n'
            '        "Error: Provide at least one verifier source via "'
        )
        snippet_xor = (
            "if (task_path is None) == (task_ref is None):\n"
            '    raise ValueError("Provide exactly one of -p/--task-path or -t/--task.")'
        )
        diff = (
            f"diff --git a/{jobs} b/{jobs}\n"
            f"--- a/{jobs}\n"
            f"+++ b/{jobs}\n"
            f"@@ -1,1 +1,8 @@\n"
            f" context\n"
            f"+if not task_paths and not task_refs and not dataset_specs:\n"
            f'+    console.print(\n'
            f'+        "Error: Provide at least one verifier source via "\n'
            f"diff --git a/{trials} b/{trials}\n"
            f"--- a/{trials}\n"
            f"+++ b/{trials}\n"
            f"@@ -1,1 +1,6 @@\n"
            f" context\n"
            f"+if (task_path is None) == (task_ref is None):\n"
            f'+    raise ValueError("Provide exactly one of -p/--task-path or -t/--task.")\n'
        )
        idx = build_diff_index(diff)
        kept, dropped = verify_candidates(
            [
                _cand(
                    file=jobs,
                    title="Missing error handling for missing verifier sources",
                    claim="regrade should handle missing verifier sources",
                    existing_code=snippet_err,
                    invariant="handle missing verifier sources",
                    violating_condition="no verifier sources",
                    execution_path=["regrade"],
                ),
                _cand(
                    file=trials,
                    title="Inconsistent task path and reference handling",
                    claim="Exactly one of task_path or task_ref should be provided",
                    existing_code=snippet_xor,
                    invariant="Exactly one of task_path or task_ref should be provided",
                    violating_condition="both or neither",
                    execution_path=["regrade"],
                ),
                _cand(
                    title="Potential missing guard for task_configs",
                    claim="removing the empty guard might be dangerous",
                    existing_code="if not task_configs:",
                    invariant="task_configs should not be empty",
                ),
            ],
            index=idx,
            llm=lambda _p: "VERIFIED",
        )
        self.assertEqual(kept, [])
        reasons = {d.get("drop_reason") for d in dropped}
        self.assertTrue(reasons & {"not_a_defect", "unproven"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
