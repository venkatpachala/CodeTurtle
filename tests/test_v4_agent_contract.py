"""V4.6 — BundleAgent defect contract. Synthetic titles only."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent.bundle_agent import BundleAgent
from core.agent.contract import classify_kind
from core.agent.parse import candidate_dict
from core.pr_facts import build_pr_facts
from core.reflector import reflect_candidate
from core.runtime.models import Bundle, Candidate
from core.runtime.review_runtime import ReviewRuntime
from core.verification.diff_index import build_diff_index

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
        title="",
        claim="",
        severity="medium",
        source="agent",
        evidence_paths=[LOADER],
        kind="defect",
    )
    base.update(kwargs)
    return Candidate(**base)


class TestClassifyKind(unittest.TestCase):
    def test_changelog_add_parameter_is_note(self):
        self.assertEqual(
            classify_kind("Add regrade parameter to foo", "added a flag"),
            "note",
        )

    def test_test_sentence_is_note(self):
        self.assertEqual(
            classify_kind("Test launch requires org", "test launch requires org"),
            "note",
        )

    def test_defect_shaped_keep(self):
        title = "validate_selection allows both source_job_id and source_trial_ids empty"
        self.assertEqual(classify_kind(title, title), "defect")


class TestParseDropsChangelog(unittest.TestCase):
    def test_parser_marks_add_regrade_as_note(self):
        d = candidate_dict(
            {
                "file": LOADER,
                "title": "Add regrade parameter to foo",
                "claim": "added regrade to foo",
                "severity": "medium",
            },
            bundle_id="B-001",
        )
        self.assertEqual(d["kind"], "note")

    def test_parser_marks_test_launch_as_note(self):
        d = candidate_dict(
            {
                "file": LOADER,
                "title": "Test launch requires org",
                "claim": "test launch requires org",
                "severity": "medium",
            },
            bundle_id="B-001",
        )
        self.assertEqual(d["kind"], "note")

    def test_parser_keeps_defect(self):
        title = "validate_selection allows both source_job_id and source_trial_ids empty"
        d = candidate_dict(
            {
                "file": LOADER,
                "title": title,
                "claim": title,
                "severity": "medium",
                "kind": "defect",
            },
            bundle_id="B-001",
        )
        self.assertEqual(d["kind"], "defect")


class TestReflectorChangelog(unittest.TestCase):
    def test_reflector_drops_changelog(self):
        idx = build_diff_index(DIFF)
        keep, reason = reflect_candidate(
            _cand(title="Add regrade parameter to foo", kind="defect"),
            files_changed=[LOADER],
            index=idx,
            line=2,
        )
        self.assertFalse(keep)
        self.assertEqual(reason, "changelog")

    def test_reflector_keeps_defect(self):
        idx = build_diff_index(DIFF)
        title = "validate_selection allows both source_job_id and source_trial_ids empty"
        keep, reason = reflect_candidate(
            _cand(
                title=title,
                claim=title,
                symbol="validate_selection",
                existing_code="def validate_selection",
                invariant="a source selector is required",
                violating_condition="both source_job_id and source_trial_ids empty",
            ),
            files_changed=[LOADER],
            index=idx,
            line=2,
        )
        self.assertTrue(keep)


class TestEmptyListNotRequestChanges(unittest.TestCase):
    def test_empty_agent_json_not_request_changes(self):
        facts = build_pr_facts(title="x", files_changed=[LOADER], full_diff=DIFF)
        result = ReviewRuntime(llm=lambda _p: "[]").run(
            files_changed=[LOADER],
            full_diff=DIFF,
            pr_facts=facts,
        )
        self.assertEqual(result.comments, [])
        self.assertNotEqual(result.decision, "REQUEST_CHANGES")

    def test_agent_changelog_payload_dropped(self):
        payload = [
            {
                "file": LOADER,
                "title": "Add regrade parameter to foo",
                "claim": "added regrade",
                "severity": "medium",
                "symbol": "foo",
                "evidence_paths": [LOADER],
            },
            {
                "file": LOADER,
                "title": "Test launch requires org",
                "claim": "test launch requires org",
                "severity": "medium",
                "evidence_paths": [LOADER],
            },
        ]
        bundle = Bundle(id="B-001", paths=[LOADER], units=[], symbols=[], kind="source")
        out = BundleAgent(llm=lambda _p: json.dumps(payload)).run(bundle)
        kinds = {c.kind for c in out}
        self.assertTrue(out)
        self.assertTrue(kinds <= {"note", "defect"})
        self.assertTrue(all(c.kind == "note" for c in out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
