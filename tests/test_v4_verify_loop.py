"""H9 VerifyLoop: snippet in hunk, falsify, hedges. Synthetic paths only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pr_facts import build_pr_facts
from core.runtime.models import Bundle, Candidate
from core.runtime.review_runtime import ReviewRuntime
from core.runtime.verify_loop import verify_candidates
from core.verification.diff_index import build_diff_index
from core.verification.policy import decide

LOADER = "pkg/api/loader.py"
DIFF = (
    f"diff --git a/{LOADER} b/{LOADER}\n"
    f"--- a/{LOADER}\n"
    f"+++ b/{LOADER}\n"
    f"@@ -1,1 +1,8 @@\n"
    f" context\n"
    f"+def validate_selection(source_job_id=None, source_trial_ids=None):\n"
    f"+    return True\n"
)


def _cand(**kwargs) -> Candidate:
    base = dict(
        bundle_id="B-001",
        file=LOADER,
        symbol="validate_selection",
        start_line=2,
        title="empty source_job_id accepted",
        claim="empty source_job_id accepted",
        existing_code="def validate_selection(source_job_id=None, source_trial_ids=None):",
        invariant="a source selector is required",
        violating_condition="both fields empty",
        execution_path=["validate_selection"],
        evidence=[LOADER],
        evidence_paths=[LOADER],
        kind="defect",
        severity="medium",
        confidence=0.8,
    )
    base.update(kwargs)
    return Candidate(**base)


class TestVerifyLoop(unittest.TestCase):
    def setUp(self):
        self.idx = build_diff_index(DIFF)
        self.bundle = Bundle(id="B-001", paths=[LOADER], units=[], kind="source")

    def test_snippet_not_in_hunk_drops(self):
        kept, dropped = verify_candidates(
            [_cand(existing_code="THIS_SNIPPET_IS_ABSENT")],
            index=self.idx,
            bundles=[self.bundle],
            llm=lambda _p: "VERIFIED",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "snippet_not_in_hunk" for d in dropped))

    def test_falsify_verified_keeps(self):
        kept, dropped = verify_candidates(
            [_cand()],
            index=self.idx,
            bundles=[self.bundle],
            llm=lambda _p: "VERIFIED the unguarded path",
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].verify_status, "verified")

    def test_falsify_disproved_drops(self):
        kept, dropped = verify_candidates(
            [_cand()],
            index=self.idx,
            bundles=[self.bundle],
            llm=lambda _p: "DISPROVED: raise ValueError already",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "disproved" for d in dropped))

    def test_hedge_not_promoted_to_verified(self):
        kept, dropped = verify_candidates(
            [
                _cand(
                    title="Potential UUID collision",
                    claim="ids may not belong to source_job",
                    confidence=0.0,
                )
            ],
            index=self.idx,
            bundles=[self.bundle],
            llm=lambda _p: "VERIFIED",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "unproven" for d in dropped))
        rec, reason = decide(
            [
                {
                    "file": LOADER,
                    "title": "Potential UUID collision",
                    "claim": "ids may not belong to source_job",
                    "severity": "nit",
                    "kind": "defect",
                    "verify_status": "uncertain",
                    "confidence": 0.0,
                }
            ],
            classification="source",
            files_changed=[LOADER],
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")
        self.assertNotEqual(reason, "verified_medium")
        self.assertNotEqual(reason, "supported_medium")

    def test_parse_fail_uncertain(self):
        kept, dropped = verify_candidates(
            [_cand()],
            index=self.idx,
            bundles=[self.bundle],
            llm=lambda _p: "not sure really",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "unproven" for d in dropped))

    def test_incomplete_proof_drops(self):
        kept, dropped = verify_candidates(
            [_cand(existing_code="", invariant="", violating_condition="")],
            index=self.idx,
            bundles=[self.bundle],
            llm=lambda _p: "VERIFIED",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "incomplete_proof" for d in dropped))

    def test_same_bundle_test_covers_invariant(self):
        bundle = Bundle(
            id="B-001",
            paths=[LOADER, "tests/test_loader.py"],
            units=[
                {
                    "path": "tests/test_loader.py",
                    "excerpt": "def test_source_selector():\n    assert source_job_id\n",
                }
            ],
            kind="source",
        )
        kept, dropped = verify_candidates(
            [_cand()],
            index=self.idx,
            bundles=[bundle],
            llm=lambda _p: "VERIFIED",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "disproved" for d in dropped))


class TestVerifyPolicy(unittest.TestCase):
    def test_hedge_trio_comment(self):
        rec, reason = decide(
            [
                {
                    "file": LOADER,
                    "title": "Potential UUID mismatch",
                    "claim": "ids may be wrong",
                    "severity": "medium",
                    "verification_status": "supported",
                    "confidence": 0.0,
                    "kind": "defect",
                }
                for _ in range(3)
            ],
            classification="source",
            files_changed=[LOADER],
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")
        self.assertNotEqual(reason, "supported_medium")
        self.assertEqual(rec, "MERGE")
        self.assertEqual(reason, "no_findings")

    def test_verified_snippet_requests_changes(self):
        rec, reason = decide(
            [
                {
                    "file": LOADER,
                    "title": "empty source_job_id accepted",
                    "claim": "empty source_job_id accepted",
                    "severity": "medium",
                    "kind": "defect",
                    "verify_status": "verified",
                    "existing_code": "def validate_selection",
                    "invariant": "selector required",
                    "violating_condition": "both empty",
                    "confidence": 0.9,
                }
            ],
            classification="source",
            files_changed=[LOADER],
        )
        self.assertEqual(rec, "REQUEST_CHANGES")
        self.assertEqual(reason, "verified_medium")

    def test_coverage_ignored(self):
        rec, reason = decide(
            [],
            classification="source",
            coverage={"units_total": 20, "units_packed": 4, "source_units": 18},
            files_changed=[LOADER],
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")
        self.assertEqual(reason, "no_findings")


class TestQualificationGate(unittest.TestCase):
    """Live #3237-shaped false positives must DROP, not COMMENT."""

    def test_guard_snippet_is_not_a_defect(self):
        jobs = "pkg/cli/jobs.py"
        snippet = (
            "if not task_paths and not task_refs and not dataset_specs:\n"
            '    console.print(\n'
            '        "Error: Provide at least one verifier source via "'
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
        )
        idx = build_diff_index(diff)
        kept, dropped = verify_candidates(
            [
                _cand(
                    file=jobs,
                    title="Missing error handling for missing verifier sources",
                    claim="regrade should handle missing verifier sources",
                    existing_code=snippet,
                    invariant="regrade should handle the case where no verifier sources are provided",
                    violating_condition="no verifier sources",
                    execution_path=["regrade"],
                    evidence=[jobs],
                    evidence_paths=[jobs],
                )
            ],
            index=idx,
            bundles=[Bundle(id="B-001", paths=[jobs], units=[], kind="source")],
            llm=lambda _p: "VERIFIED",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "not_a_defect" for d in dropped))

    def test_raise_valueerror_is_not_a_defect(self):
        trials = "pkg/cli/trials.py"
        snippet = (
            "if (task_path is None) == (task_ref is None):\n"
            '    raise ValueError("Provide exactly one of -p/--task-path or -t/--task.")'
        )
        diff = (
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
                    file=trials,
                    title="Inconsistent task path and reference handling",
                    claim="Exactly one of task_path or task_ref should be provided",
                    existing_code=snippet,
                    invariant="Exactly one of task_path or task_ref should be provided",
                    violating_condition="both or neither supplied",
                    execution_path=["regrade"],
                    evidence=[trials],
                    evidence_paths=[trials],
                )
            ],
            index=idx,
            bundles=[Bundle(id="B-001", paths=[trials], units=[], kind="source")],
            llm=lambda _p: "UNCERTAIN",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "not_a_defect" for d in dropped))

    def test_potential_guard_is_unproven(self):
        kept, dropped = verify_candidates(
            [
                _cand(
                    title="Potential missing guard for task_configs",
                    claim="removing the empty guard might be dangerous",
                    existing_code="if not task_configs:",
                    invariant="task_configs should not be empty",
                    violating_condition="empty task_configs",
                )
            ],
            index=build_diff_index(DIFF),
            bundles=[Bundle(id="B-001", paths=[LOADER], units=[], kind="source")],
            llm=lambda _p: "VERIFIED",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "unproven" for d in dropped))

    def test_unproven_n_trials_drops(self):
        kept, dropped = verify_candidates(
            [_cand()],
            index=build_diff_index(DIFF),
            bundles=[Bundle(id="B-001", paths=[LOADER], units=[], kind="source")],
            llm=lambda _p: "UNCERTAIN cannot trace consumers",
        )
        self.assertEqual(kept, [])
        self.assertTrue(any(d.get("drop_reason") == "unproven" for d in dropped))


class TestRuntimeHedgesNotRc(unittest.TestCase):
    def test_potential_agent_output_not_request_changes(self):
        payload = [
            {
                "file": LOADER,
                "title": "Potential UUID collision",
                "claim": "ids may not belong to source_job",
                "severity": "medium",
                "confidence": 0.0,
                "kind": "defect",
                "existing_code": "def validate_selection(source_job_id=None, source_trial_ids=None):",
                "invariant": "trial ids must belong to source_job",
                "violating_condition": "mismatched job id",
                "execution_path": ["validate_selection"],
                "evidence": [LOADER],
            }
        ]
        import json

        facts = build_pr_facts(title="x", files_changed=[LOADER], full_diff=DIFF)
        def llm(prompt: str) -> str:
            if "You only try to DISPROVE" in prompt:
                return "UNCERTAIN"
            return json.dumps(payload)

        result = ReviewRuntime(llm=llm).run(
            files_changed=[LOADER],
            full_diff=DIFF,
            pr_facts=facts,
        )
        self.assertNotEqual(result.decision, "REQUEST_CHANGES")
        self.assertNotEqual(result.policy_reason, "supported_medium")


if __name__ == "__main__":
    unittest.main(verbosity=2)
