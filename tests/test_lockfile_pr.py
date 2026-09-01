"""Lockfile-only PRs (571 gap): classify, repair, skip investigate, no 538 regression."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.finding_validator import (
    filter_findings,
    normalize_findings,
    repair_finding_paths,
    validate_finding,
)
from core.investigation.loop import run_investigation
from core.pr_facts import build_pr_facts, classify_change_set, format_pr_facts_for_prompt
from core.pr_understanding import refine_understanding
from core.models import PRUnderstanding

LOCK = "package-lock.json"
LOADER = "api/loaders/sqlserver_loader.py"
WORDLIST = ".github/wordlist.txt"


class TestClassification(unittest.TestCase):
    def test_lockfile_only(self):
        kind = classify_change_set([LOCK])
        self.assertEqual(kind["classification"], "lockfile-only")
        self.assertEqual(kind["lock_files"], [LOCK])
        self.assertEqual(kind["source_files"], [])

    def test_source_and_mixed(self):
        src = classify_change_set([LOADER, WORDLIST])
        self.assertEqual(src["classification"], "source")
        mixed = classify_change_set([LOADER, LOCK])
        self.assertEqual(mixed["classification"], "mixed")

    def test_pr_facts_fields_and_prompt(self):
        facts = build_pr_facts(files_changed=[LOCK], title="chore: lockfile")
        self.assertEqual(facts["classification"], "lockfile-only")
        self.assertEqual(facts["lock_files"], [LOCK])
        block = format_pr_facts_for_prompt(facts)
        self.assertIn("classification: lockfile-only", block)
        self.assertIn("lock_files:", block)
        self.assertIn(LOCK, block)


class TestLockfileRepair(unittest.TestCase):
    def test_dep_title_empty_file_repairs_and_keeps(self):
        facts = build_pr_facts(files_changed=[LOCK])
        raw = [{"title": "Dependency Update", "claim": "npm lockfile version bump"}]
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = normalize_findings(raw, files_changed=[LOCK], pr_facts=facts)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file"], LOCK)
        self.assertEqual(out[0]["evidence"], [LOCK])
        self.assertTrue(out[0].get("_path_repaired"))
        self.assertIn(f"[Grounding] REPAIR file={LOCK}", buf.getvalue())
        ok, reason = validate_finding(
            out[0], files_changed=[LOCK], paths_in_diff=[LOCK]
        )
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

    def test_generic_naming_no_repair_drop(self):
        facts = build_pr_facts(files_changed=[LOCK])
        raw = [{"title": "Naming and Documentation", "claim": "names could be clearer"}]
        out = normalize_findings(raw, files_changed=[LOCK], pr_facts=facts)
        self.assertTrue(out)
        self.assertFalse(out[0].get("file"))
        self.assertFalse(out[0].get("_path_repaired"))
        ok, reason = validate_finding(
            out[0], files_changed=[LOCK], paths_in_diff=[LOCK]
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_evidence_path")

    def test_source_pr_wordlist_still_trivial_drop(self):
        facts = build_pr_facts(files_changed=[LOADER, WORDLIST])
        self.assertEqual(facts["classification"], "source")
        raw = [
            {
                "title": "Naming and Documentation",
                "evidence": [WORDLIST],
                "claim": "wordlist nit",
            }
        ]
        out = normalize_findings(raw, files_changed=[LOADER, WORDLIST], pr_facts=facts)
        self.assertFalse(out[0].get("_path_repaired"))
        ok, reason = validate_finding(
            out[0],
            files_changed=[LOADER, WORDLIST],
            paths_in_diff=[LOADER, WORDLIST],
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "trivial_evidence_only")

    def test_source_loader_cite_still_keep(self):
        facts = build_pr_facts(files_changed=[LOADER, WORDLIST])
        raw = [
            {
                "title": "load_schema swallows errors",
                "file": LOADER,
                "evidence": [LOADER],
            }
        ]
        out = normalize_findings(raw, files_changed=[LOADER, WORDLIST], pr_facts=facts)
        ok, reason = validate_finding(
            out[0],
            files_changed=[LOADER, WORDLIST],
            paths_in_diff=[LOADER, WORDLIST],
        )
        self.assertTrue(ok, reason)

    def test_lockfile_not_trivial(self):
        ok, reason = validate_finding(
            {"title": "Dependency Update", "file": LOCK, "evidence": [LOCK]},
            files_changed=[LOCK],
            paths_in_diff=[LOCK],
        )
        self.assertTrue(ok, reason)

    def test_repair_does_not_overwrite_existing_evidence(self):
        finding = {
            "title": "Dependency Update",
            "evidence": [LOCK],
            "file": LOCK,
        }
        out = repair_finding_paths(
            dict(finding),
            [LOCK],
            classification="lockfile-only",
            lock_files=[LOCK],
        )
        self.assertEqual(out["evidence"], [LOCK])
        self.assertFalse(out.get("_path_repaired"))


class TestInvestigateSkipLockfile(unittest.TestCase):
    def test_lockfile_only_skips_investigation(self):
        class Boom:
            def get_node(self, *a, **k):
                raise AssertionError("no Graphify hop on lockfile PR")

            get_neighbors = get_node
            query = get_node
            get_pr_impact = get_node

        facts = build_pr_facts(files_changed=[LOCK], pr_number=571)
        finding = {
            "id": "f-1",
            "title": "Dependency Update",
            "file": LOCK,
            "evidence": [LOCK],
            "claim": "lockfile version bump",
        }
        state = {
            "repo": "FalkorDB/QueryWeaver",
            "number": 571,
            "files_changed": [LOCK],
            "full_diff": "",
            "pr_facts": facts,
            "validated_findings": [finding],
            "findings": [finding],
            "review_plan": {"investigate": [{"file": LOCK, "ask": "neighbors"}]},
        }
        out = run_investigation(state, Boom())
        self.assertTrue(out["investigation_report"]["skipped"])
        self.assertEqual(
            out["investigation_report"]["reason"], "no_changed_path_hypotheses"
        )


class TestUnderstandingAndFinal(unittest.TestCase):
    def test_refine_forces_dependencies_and_lock_summary(self):
        facts = build_pr_facts(files_changed=[LOCK], title="Add ARM64 support")
        u = PRUnderstanding(
            summary="Add ARM64 support for native builds",
            change_type=["feature"],
            risk_level="low",
        )
        out = refine_understanding(u, files=[LOCK], body="", pr_facts=facts)
        self.assertIn("dependencies", [c.lower() for c in out.change_type])
        self.assertTrue(
            any(
                t in out.summary.lower()
                for t in ("lock", "dependenc", "package-lock")
            )
        )

    def test_prompt_builder_includes_classification(self):
        facts = build_pr_facts(files_changed=[LOCK])
        block = format_pr_facts_for_prompt(facts)
        self.assertIn("classification: lockfile-only", block)
        self.assertIn("lockfile-only", block)

    def test_final_policy_b_comment_when_lockfile_kept_zero(self):
        from core.agents import final_recommender
        from core.models import ReviewOutput

        captured = {}

        def fake_gen(**kwargs):
            captured["prompt"] = kwargs.get("prompt") or ""
            return ReviewOutput(
                summary="lockfile-only; no grounded issue",
                recommendation="COMMENT",
                confidence=0.5,
            )

        state = {
            "validated_findings": [],
            "findings": [],
            "pr_facts": {"classification": "lockfile-only", "lock_files": [LOCK]},
            "pr_understanding": {"summary": "lockfile sync", "risk_level": "low"},
            "review_plan": {"risk_level": "low"},
        }
        with patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            out = final_recommender(state)
        self.assertEqual(out["recommendation"], "COMMENT")
        prompt = captured.get("prompt") or ""
        self.assertIn("COMMENT", prompt)
        self.assertIn("lockfile-only", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
