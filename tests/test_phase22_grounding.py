"""Phase 2.2 grounding: normalizer, validator L1–L5, diffstat, retrieval hygiene."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.finding_validator import (
    filter_findings,
    log_validation,
    normalize_findings,
    repair_finding_paths,
    validate_finding,
    validate_findings_node,
)
from core.pr_facts import (
    build_pr_facts,
    extract_diff_symbols,
    question_grounded_in_pr,
    dedupe_near_duplicate_questions,
)


LOADER = "api/loaders/sqlserver_loader.py"
WORDLIST = ".github/wordlist.txt"
GITIGNORE = ".gitignore"

DIFF = f"""diff --git a/{LOADER} b/{LOADER}
--- a/{LOADER}
+++ b/{LOADER}
@@ -40,6 +40,10 @@ class SQLServerLoader:
     def load_schema(self):
         cursor = self.connection.cursor()
+        if not cursor:
+            raise RuntimeError("no cursor")
         return cursor.fetchall()

diff --git a/{WORDLIST} b/{WORDLIST}
--- a/{WORDLIST}
+++ b/{WORDLIST}
@@ -1,0 +1,1 @@
+sqlserver
"""

FILES = [LOADER, WORDLIST, GITIGNORE]


def _facts():
    return build_pr_facts(
        title="Fix SQL Server loader",
        files_changed=FILES,
        full_diff=DIFF,
        pr_number=538,
        repo="owner/queryweaver",
    )


class TestDiffstat(unittest.TestCase):
    def test_git_headers_count_files(self):
        facts = _facts()
        self.assertGreaterEqual(facts["diff_stat"]["files_in_diff"], 2)
        self.assertIn(LOADER, facts["files_changed"])
        self.assertIn(LOADER, facts["paths_in_diff"])
        self.assertGreater(facts["diff_bytes"], 100)

    def test_github_style_headers_without_diff_git(self):
        # Old construction: `--- filename` / `+++ filename` + hunk only
        githubish = (
            f"--- {LOADER}\n+++ {LOADER}\n"
            "@@ -1,1 +1,2 @@\n"
            " def load_schema():\n"
            "+    pass\n"
        )
        facts = build_pr_facts(files_changed=[LOADER], full_diff=githubish)
        self.assertGreaterEqual(facts["diff_stat"]["files_in_diff"], 1)
        self.assertIn(LOADER, facts["paths_in_diff"])

    def test_empty_diff_with_files_still_lists_github_paths(self):
        facts = build_pr_facts(files_changed=[LOADER], full_diff="")
        self.assertEqual(facts["file_count"], 1)
        self.assertEqual(facts["diff_stat"]["files_in_diff"], 0)

    def test_extract_def_class_from_diff(self):
        syms = extract_diff_symbols(DIFF)
        self.assertIn("SQLServerLoader", syms)
        self.assertIn("load_schema", syms)


class TestNormalizer(unittest.TestCase):
    def test_copy_evidence_path_to_file(self):
        out = normalize_findings(
            [{"title": "X", "evidence": [LOADER], "claim": "load_schema can raise"}]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file"], LOADER)
        self.assertEqual(out[0]["evidence"][0], LOADER)

    def test_normalize_slashes_and_drop_empty_and_dupes(self):
        raw = [
            {"title": "", "claim": "", "description": ""},
            {"title": "Same", "file": r"api\loaders\sqlserver_loader.py"},
            {"title": "Same", "file": LOADER},
            {"title": "Other", "file": LOADER},
        ]
        out = normalize_findings(raw)
        titles = [f["title"] for f in out]
        self.assertEqual(titles, ["Same", "Other"])
        self.assertEqual(out[0]["file"], LOADER)

    def test_flatten_pydantic_and_json_string(self):
        from core.models import Finding

        f = Finding(title="Typed", file=LOADER, evidence=[LOADER], claim="x")
        out = normalize_findings([f, '{"title": "FromJSON", "file": "%s"}' % LOADER])
        self.assertEqual({x["title"] for x in out}, {"Typed", "FromJSON"})

    def test_story_symbol_stripped(self):
        out = normalize_findings(
            [{"title": "X", "file": LOADER, "symbol": "this is a whole sentence"}]
        )
        self.assertIsNone(out[0]["symbol"])


class TestValidator(unittest.TestCase):
    def _check(self, finding, **extra):
        facts = _facts()
        return validate_finding(
            finding,
            files_changed=facts["files_changed"],
            paths_in_diff=facts["paths_in_diff"],
            changed_symbols=extract_diff_symbols(DIFF),
            full_diff=DIFF,
            **extra,
        )

    def test_l1_missing_evidence(self):
        ok, reason = self._check({"title": "Hunch", "claim": "something is wrong"})
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_evidence_path")

    def test_l2_evidence_not_in_pr(self):
        ok, reason = self._check(
            {
                "title": "Unrelated",
                "file": "lib/fake.py",
                "evidence": ["lib/fake.py"],
            }
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "evidence_not_in_pr")

    def test_l3_wordlist_cannot_keep_python_finding(self):
        ok, reason = self._check(
            {
                "title": "Naming and Documentation",
                "evidence": [WORDLIST],
                "claim": "names are unclear",
            }
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "trivial_evidence_only")

    def test_l3_gitignore_and_license(self):
        for path in (GITIGNORE, "LICENSE"):
            finding = {"title": "Nit", "file": path, "evidence": [path]}
            ok, reason = validate_finding(
                finding,
                files_changed=[LOADER, path],
                paths_in_diff=[LOADER, path],
            )
            self.assertFalse(ok, path)
            self.assertEqual(reason, "trivial_evidence_only")

    def test_recall_keep_when_file_is_the_changed_source(self):
        ok, reason = self._check(
            {
                "id": "CQ-1",
                "title": "load_schema swallows errors",
                "claim": "SQLServerLoader.load_schema does not raise on a dead cursor",
                "file": LOADER,
                "evidence": [LOADER],
                "symbol": "SQLServerLoader.load_schema",
                "severity": "concern",
            }
        )
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

    def test_basename_evidence_maps_to_changed_path(self):
        ok, reason = self._check(
            {
                "title": "Cursor handling",
                "file": "sqlserver_loader.py",
                "evidence": ["sqlserver_loader.py"],
            }
        )
        self.assertTrue(ok, reason)

    def test_l5_unknown_symbol(self):
        ok, reason = self._check(
            {
                "title": "Fake helper",
                "file": LOADER,
                "evidence": [LOADER],
                "symbol": "FakeCursor",
            }
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "unknown_symbol")

    def test_l5_skipped_when_no_symbols_extracted(self):
        ok, reason = validate_finding(
            {
                "title": "X",
                "file": LOADER,
                "evidence": [LOADER],
                "symbol": "Whatever",
            },
            files_changed=[LOADER],
            changed_symbols=[],
            full_diff="",
        )
        self.assertTrue(ok)


class TestLogsAndNode(unittest.TestCase):
    def test_drop_keep_log_format(self):
        findings = [
            {
                "title": "Naming and Documentation",
                "evidence": [WORDLIST],
                "file": WORDLIST,
            },
            {
                "title": "load_schema swallows errors",
                "file": LOADER,
                "evidence": [LOADER],
            },
        ]
        facts = _facts()
        result = filter_findings(
            normalize_findings(findings),
            files_changed=facts["files_changed"],
            paths_in_diff=facts["paths_in_diff"],
            changed_symbols=extract_diff_symbols(DIFF),
            full_diff=DIFF,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            log_validation(result)
        text = buf.getvalue()
        self.assertIn("[Grounding] DROP reason=trivial_evidence_only", text)
        self.assertIn("title=Naming and Documentation", text)
        self.assertIn("evidence=", text)
        self.assertIn("[Grounding] KEEP", text)
        self.assertIn(f"file={LOADER}", text)
        self.assertIn("[Grounding] raw=", text)
        self.assertIn("kept=1", text)
        self.assertIn("dropped=1", text)

    def test_validate_node_same_list_for_display_and_critic(self):
        state = {
            "files_changed": FILES,
            "full_diff": DIFF,
            "pr_facts": _facts(),
            "correctness_findings": [
                {
                    "title": "Naming and Documentation",
                    "evidence": [WORDLIST],
                    "category": "correctness",
                },
                {
                    "title": "load_schema swallows errors",
                    "file": LOADER,
                    "evidence": [LOADER],
                    "category": "correctness",
                },
            ],
            "quality_findings": [
                {"title": "Ghost", "file": "not/in/pr.py", "evidence": ["not/in/pr.py"]}
            ],
            "testing_findings": [],
            "correctness_meta": {"raw": 2, "grounded": 2},
            "quality_meta": {"raw": 1, "grounded": 1},
            "testing_meta": {"skipped": True, "raw": 0, "grounded": 0},
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = validate_findings_node(state)
        self.assertEqual(len(out["validated_findings"]), 1)
        self.assertEqual(out["validated_findings"], out["findings"])
        self.assertEqual(out["validated_findings"], out["correctness_findings"])
        self.assertEqual(out["quality_findings"], [])
        self.assertEqual(out["correctness_meta"]["grounded"], 1)
        self.assertEqual(out["correctness_meta"]["raw"], 2)
        self.assertTrue(out["validation_report"]["ran"])
        self.assertEqual(out["validation_report"]["kept"], 1)
        self.assertEqual(out["findings"][0]["file"], LOADER)


class TestPathRepair(unittest.TestCase):
    def _validate(self, finding):
        facts = _facts()
        return validate_finding(
            finding,
            files_changed=facts["files_changed"],
            paths_in_diff=facts["paths_in_diff"],
            changed_symbols=extract_diff_symbols(DIFF),
            full_diff=DIFF,
        )

    def test_empty_evidence_mentions_loader_repaired_keep(self):
        raw = [
            {
                "title": "Error handling in sqlserver_loader.py",
                "claim": "load_schema does not raise on a dead cursor",
            }
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = normalize_findings(raw, files_changed=FILES)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file"], LOADER)
        self.assertEqual(out[0]["evidence"], [LOADER])
        self.assertTrue(out[0].get("_path_repaired"))
        self.assertIn(f"[Grounding] REPAIR file={LOADER}", buf.getvalue())
        ok, reason = self._validate(out[0])
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

    def test_generic_naming_still_drop(self):
        raw = [{"title": "Naming", "claim": "names could be clearer"}]
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = normalize_findings(raw, files_changed=FILES)
        self.assertTrue(out)
        self.assertFalse(out[0].get("file"))
        self.assertFalse(out[0].get("evidence"))
        self.assertFalse(out[0].get("_path_repaired"))
        self.assertNotIn("[Grounding] REPAIR", buf.getvalue())
        ok, reason = self._validate(out[0])
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_evidence_path")

    def test_wordlist_evidence_not_overwritten_still_drop(self):
        raw = [
            {
                "title": "Naming and sqlserver_loader.py documentation",
                "evidence": [WORDLIST],
            }
        ]
        out = normalize_findings(raw, files_changed=FILES)
        self.assertEqual(out[0]["evidence"], [WORDLIST])
        self.assertFalse(out[0].get("_path_repaired"))
        # repair_finding_paths itself must no-op when evidence is already set
        repaired = repair_finding_paths(
            {"title": "sqlserver_loader.py nit", "evidence": [WORDLIST]},
            FILES,
        )
        self.assertEqual(repaired["evidence"], [WORDLIST])
        self.assertFalse(repaired.get("_path_repaired"))
        ok, reason = self._validate(out[0])
        self.assertFalse(ok)
        self.assertEqual(reason, "trivial_evidence_only")

    def test_tsx_basename_repair(self):
        tsx = "frontend/src/DatabaseModal.tsx"
        raw = [{"title": "DatabaseModal.tsx prop types are missing"}]
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = normalize_findings(raw, files_changed=[tsx, WORDLIST])
        self.assertEqual(out[0]["file"], tsx)
        self.assertTrue(out[0].get("_path_repaired"))
        self.assertIn(f"[Grounding] REPAIR file={tsx}", buf.getvalue())


class TestQuestionFilter(unittest.TestCase):
    def test_drops_invented_symbols(self):
        self.assertFalse(
            question_grounded_in_pr(
                "How does FakeConnection interact with FakeCursor?",
                FILES,
                DIFF,
            )
        )
        self.assertFalse(
            question_grounded_in_pr("Callers of FakeCursor", FILES, DIFF)
        )
        # mixed real + invented still drops — Fake* must not ride along
        self.assertFalse(
            question_grounded_in_pr(
                "Callers of load_schema and FakeCursor",
                FILES,
                DIFF,
            )
        )

    def test_planner_strips_fake_symbols(self):
        from core.review_intelligence.models import RetrievalQuestion
        from core.review_intelligence.planner import (
            _deterministic_questions,
            _filter_grounded_questions,
        )

        qs = _filter_grounded_questions(
            [
                RetrievalQuestion(question="Callers of FakeCursor"),
                RetrievalQuestion(question="Definition of FakeConnection"),
                RetrievalQuestion(question="Definition of load_schema"),
            ],
            FILES,
            DIFF,
        )
        blob = " ".join(q.question for q in qs)
        self.assertNotIn("FakeCursor", blob)
        self.assertNotIn("FakeConnection", blob)
        self.assertIn("load_schema", blob)

        generated = _deterministic_questions(
            {"summary": "fix loader"},
            {
                "changed_files": FILES,
                "full_diff": DIFF,
                "modified_functions": ["load_schema", "FakeConnection"],
                "added_functions": ["FakeCursor"],
            },
        )
        generated = _filter_grounded_questions(generated, FILES, DIFF)
        blob = " ".join(q.question for q in generated)
        self.assertNotIn("FakeConnection", blob)
        self.assertNotIn("FakeCursor", blob)

    def test_keeps_real_path_or_diff_ident(self):
        self.assertTrue(
            question_grounded_in_pr(
                "Definition of load_schema and how it handles parameters",
                FILES,
                DIFF,
            )
        )
        self.assertTrue(
            question_grounded_in_pr(
                f"Callers of {LOADER}",
                FILES,
                DIFF,
            )
        )

    def test_dedupe_near_duplicates(self):
        qs = [
            "Definition of load_schema and how it handles parameters",
            "Definition of load_schema and how it handles return values",
            "Tests covering SQLServerLoader",
        ]
        out = dedupe_near_duplicate_questions(qs)
        self.assertEqual(len(out), 2)


class TestEvidencePackageSingleRetrieve(unittest.TestCase):
    def test_one_graphify_retrieve(self):
        from langchain_core.documents import Document
        from core.agents import build_evidence_package

        class FakeRetriever:
            calls = []

            def __init__(self, repo):
                self.repo = repo

            def retrieve(self, query, k=8, **kwargs):
                type(self).calls.append({"query": query, "kwargs": kwargs})
                return [Document(page_content="graph ctx", metadata={"path": LOADER})]

        FakeRetriever.calls = []
        plan = {
            "intent_summary": "fix loader",
            "risk_level": "medium",
            "reviewers": ["correctness"],
            "retrieval_questions": [
                {"question": "Definition of load_schema", "purpose": "changed_symbol"},
                {"question": "Callers of FakeCursor", "purpose": "blast_radius"},
                {"question": "Definition of load_schema again", "purpose": "changed_symbol"},
            ],
        }
        state = {
            "repo": "owner/queryweaver",
            "title": "Fix SQL Server loader",
            "body": "",
            "files_changed": FILES,
            "full_diff": DIFF,
            "review_plan": plan,
            "pr_understanding": {},
            "number": 538,
        }
        with patch(
            "core.repository_knowledge.structural.graph_available", return_value=True
        ), patch(
            "core.graphify_retriever.GraphifyRetriever", FakeRetriever
        ):
            out = build_evidence_package(state)
        self.assertEqual(len(FakeRetriever.calls), 1)
        query = FakeRetriever.calls[0]["query"]
        self.assertIn(LOADER, query)
        self.assertIn("load_schema", query)
        self.assertNotIn("FakeCursor", query)
        self.assertIn("retrieve=1", out["traces"][0]["output"])


class TestCriticAndFinalSurvivorsOnly(unittest.TestCase):
    def test_critic_empty_skips_llm_and_does_not_invent(self):
        from core.agents import critic_agent

        state = {
            "title": "Fix loader",
            "files_changed": FILES,
            "full_diff": DIFF,
            "pr_facts": _facts(),
            "validated_findings": [],
            "findings": [],
            "validation_report": {
                "ran": True,
                "raw": 9,
                "kept": 0,
                "dropped": 9,
                "dropped_summaries": [
                    {
                        "title": "Naming and Documentation",
                        "reason": "trivial_evidence_only",
                        "evidence": [WORDLIST],
                    }
                ],
            },
        }
        with patch("core.agents.gateway") as gw:
            out = critic_agent(state)
            gw.generate_structured.assert_not_called()
        self.assertEqual(out["findings"], [])
        self.assertEqual(out["critique"]["kept"], [])
        self.assertIn("no validated findings", out["critique"]["notes"])

    def test_critic_prompt_does_not_include_dropped_titles(self):
        from core.agents import critic_agent
        from core.models import Findings, Finding

        captured = {}

        def fake_gen(**kwargs):
            captured["prompt"] = kwargs.get("prompt") or ""
            return Findings(
                findings=[
                    Finding(
                        title="load_schema swallows errors",
                        file=LOADER,
                        evidence=[LOADER],
                        claim="raises missing",
                    )
                ]
            )

        survivor = {
            "title": "load_schema swallows errors",
            "file": LOADER,
            "evidence": [LOADER],
            "claim": "raises missing",
            "category": "correctness",
            "severity": "concern",
        }
        state = {
            "title": "Fix loader",
            "files_changed": FILES,
            "full_diff": DIFF,
            "pr_facts": _facts(),
            "validated_findings": [survivor],
            "findings": [survivor],
            "validation_report": {
                "ran": True,
                "raw": 2,
                "kept": 1,
                "dropped": 1,
                "dropped_summaries": [
                    {"title": "Naming and Documentation", "reason": "trivial_evidence_only"}
                ],
            },
        }
        with patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            out = critic_agent(state)
        prompt = captured.get("prompt") or ""
        self.assertNotIn("Naming and Documentation", prompt)
        self.assertIn("load_schema swallows errors", prompt)
        self.assertEqual(len(out["findings"]), 1)
        self.assertEqual(out["findings"][0]["file"], LOADER)

    def test_final_empty_does_not_quote_dropped_titles(self):
        from core.agents import final_recommender
        from core.models import ReviewOutput

        captured = {}

        def fake_gen(**kwargs):
            captured["prompt"] = kwargs.get("prompt") or ""
            return ReviewOutput(
                summary="No validated findings.",
                recommendation="MERGE",
                confidence=0.7,
            )

        state = {
            "title": "Fix loader",
            "validated_findings": [],
            "findings": [],
            "pr_understanding": {"summary": "Fix loader", "risk_level": "medium"},
            "correctness_meta": {"summary": "Naming and Documentation looks bad"},
            "quality_meta": {"summary": "wordlist nits"},
            "testing_meta": {"summary": ""},
        }
        with patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            out = final_recommender(state)
        prompt = captured.get("prompt") or ""
        self.assertNotIn("Naming and Documentation", prompt)
        self.assertIn("VALIDATED findings", prompt)
        self.assertIn("(none)", prompt)
        self.assertEqual(out["recommendation"], "MERGE")
        self.assertIn("no validated", (out["merge_decision"]["summary"] or "").lower())

    def test_decision_enum_not_hardcoded(self):
        from core.agents import final_recommender
        from core.models import ReviewOutput

        for rec in ("MERGE", "COMMENT", "REQUEST_CHANGES"):
            def fake_gen(rec=rec, **kwargs):
                return ReviewOutput(summary="x", recommendation=rec, confidence=0.5)

            state = {
                "validated_findings": [
                    {
                        "title": "load_schema swallows errors",
                        "file": LOADER,
                        "evidence": [LOADER],
                        "severity": "concern",
                    }
                ],
                "pr_understanding": {"summary": "fix", "risk_level": "medium"},
            }
            with patch("core.agents.gateway") as gw:
                gw.generate_structured.side_effect = fake_gen
                out = final_recommender(state)
            self.assertEqual(out["recommendation"], rec)


class TestGraphHasValidatorNode(unittest.TestCase):
    def test_node_present(self):
        from core.graph import build_review_graph

        g = build_review_graph()
        nodes = set(g.get_graph().nodes)
        self.assertIn("validate_findings", nodes)
        self.assertIn("investigate", nodes)
        self.assertIn("critic_agent", nodes)
        self.assertNotIn("qdrant", str(nodes).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
