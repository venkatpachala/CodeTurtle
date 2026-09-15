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
        kept, _dropped = verify_candidates(
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
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].verify_status, "uncertain")
        rec, reason = decide(
            [
                {
                    "file": LOADER,
                    "title": kept[0].title,
                    "claim": kept[0].claim,
                    "severity": kept[0].severity,
                    "kind": "defect",
                    "verify_status": kept[0].verify_status,
                    "confidence": 0.0,
                }
            ],
            classification="source",
            files_changed=[LOADER],
        )
        self.assertEqual(rec, "COMMENT")
        self.assertNotEqual(reason, "verified_medium")
        self.assertNotEqual(reason, "supported_medium")

    def test_parse_fail_uncertain(self):
        kept, _dropped = verify_candidates(
            [_cand()],
            index=self.idx,
            bundles=[self.bundle],
            llm=lambda _p: "not sure really",
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].verify_status, "uncertain")

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
        kept, _dropped = verify_candidates(
            [_cand()],
            index=self.idx,
            bundles=[bundle],
            llm=lambda _p: "VERIFIED",
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].verify_status, "uncertain")


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
        self.assertEqual(rec, "COMMENT")
        self.assertNotEqual(reason, "supported_medium")
        self.assertEqual(reason, "uncertain_only")

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
