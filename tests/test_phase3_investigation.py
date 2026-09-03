"""Phase 3 investigation: budget, skip, Fake* stripped, KEEP after neighbors."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.finding_validator import validate_finding
from core.investigation.loop import run_investigation
from core.investigation.models import EvidenceItem, Hypothesis
from core.investigation.planner import (
    MAX_GRAPHIFY_CALLS_IN_INVESTIGATE,
    deterministic_investigate_asks,
    findings_to_hypotheses,
    plan_graphify_calls,
    strip_ungrounded_symbol,
)
from core.pr_facts import build_pr_facts
from core.repository_knowledge.models import GraphNode, KnowledgeQueryResult, NeighborResult, PRImpact

LOADER = "api/loaders/sqlserver_loader.py"
SCHEMA = "api/core/schema_loader.py"
PIPELINE = "api/core/pipeline.py"
WORDLIST = ".github/wordlist.txt"
DIFF = f"""diff --git a/{LOADER} b/{LOADER}
--- a/{LOADER}
+++ b/{LOADER}
@@ -1,3 +1,8 @@
 class SQLServerLoader:
     def load_schema(self):
         pass
+    def connect(self):
+        cursor = self.connection.cursor()
+        return cursor
"""
FILES = [LOADER, SCHEMA, PIPELINE, WORDLIST]


class FakeProvider:
    def __init__(self, neighbors_text="CALLS pipeline.load"):
        self.calls = []
        self.neighbors_text = neighbors_text

    def get_node(self, label):
        self.calls.append(("get_node", label))
        return GraphNode(id=label, label=label, raw={"text": f"node {label}"})

    def get_neighbors(self, label, relation_filter=None):
        self.calls.append(("get_neighbors", label))
        return NeighborResult(
            node=GraphNode(id=label, label=label),
            raw_text=self.neighbors_text,
        )

    def query(self, question, depth=3):
        self.calls.append(("query", question))
        return KnowledgeQueryResult(question=question, raw_text=f"query:{question}")

    def get_pr_impact(self, pr_number, repo=None):
        self.calls.append(("get_pr_impact", pr_number))
        return PRImpact(pr_number=pr_number, repo=repo, raw_text="impact ok")

    def investigate_file(self, path, symbol=None):
        self.calls.append(("investigate_file", path, symbol))
        label = symbol or path.split("/")[-1]
        self.get_node(label)
        self.get_neighbors(label)
        return [
            {"kind": "node", "path": path, "text": f"node {label}"},
            {"kind": "neighbors", "path": path, "text": self.neighbors_text},
        ]


def _state(findings, extra=None):
    facts = build_pr_facts(
        title="SQL Server loader",
        files_changed=FILES,
        full_diff=DIFF,
        pr_number=538,
        repo="FalkorDB/QueryWeaver",
    )
    st = {
        "repo": "FalkorDB/QueryWeaver",
        "number": 538,
        "title": "SQL Server loader",
        "files_changed": FILES,
        "full_diff": DIFF,
        "pr_facts": facts,
        "validated_findings": findings,
        "findings": findings,
        "review_plan": {"investigate": [], "risk_level": "medium"},
        "pr_understanding": {"risk_level": "low", "summary": "add loader"},
    }
    if extra:
        st.update(extra)
    return st


class TestSkipAndBudget(unittest.TestCase):
    def test_skip_when_no_kept_findings(self):
        provider = FakeProvider()
        out = run_investigation(_state([]), provider)
        self.assertTrue(out["investigation_report"]["skipped"])
        self.assertEqual(out["investigation_report"]["reason"], "no_changed_path_hypotheses")
        self.assertEqual(provider.calls, [])

    def test_skip_wordlist_only(self):
        provider = FakeProvider()
        findings = [
            {
                "id": "f-w",
                "title": "Naming",
                "file": WORDLIST,
                "evidence": [WORDLIST],
                "claim": "wordlist nit",
            }
        ]
        out = run_investigation(_state(findings), provider)
        self.assertTrue(out["investigation_report"]["skipped"])
        self.assertEqual(provider.calls, [])

    def test_budget_cap(self):
        provider = FakeProvider()
        findings = [
            {
                "id": f"f-{i}",
                "title": f"claim {name}",
                "file": name,
                "evidence": [name],
                "claim": f"check {name}",
                "symbol": "SQLServerLoader",
                "needs_investigation": True,
                "question": "who calls SQLServerLoader",
            }
            for i, name in enumerate([LOADER, SCHEMA, PIPELINE])
        ]
        out = run_investigation(_state(findings), provider)
        self.assertFalse(out["investigation_report"]["skipped"])
        self.assertLessEqual(len(provider.calls), MAX_GRAPHIFY_CALLS_IN_INVESTIGATE)
        self.assertLessEqual(out["investigation_report"]["calls"], MAX_GRAPHIFY_CALLS_IN_INVESTIGATE)
        self.assertLessEqual(len(out["hypotheses"]), 3)


class TestFakeStripped(unittest.TestCase):
    def test_fake_symbol_never_in_tool_plan(self):
        self.assertIsNone(
            strip_ungrounded_symbol("FakeCursor", FILES, DIFF)
        )
        self.assertIsNone(
            strip_ungrounded_symbol("FakeConnection", FILES, DIFF)
        )
        self.assertEqual(
            strip_ungrounded_symbol("SQLServerLoader", FILES, DIFF),
            "SQLServerLoader",
        )

    def test_fake_cursor_does_not_trigger_query_hop(self):
        provider = FakeProvider()
        findings = [
            {
                "id": "f-1",
                "title": "cursor leak",
                "file": LOADER,
                "evidence": [LOADER],
                "claim": "connect may leak",
                "symbol": "FakeCursor",
                "question": "who uses FakeCursor",
                "needs_investigation": True,
            }
        ]
        out = run_investigation(_state(findings), provider)
        blob = " ".join(str(c) for c in provider.calls)
        self.assertNotIn("FakeCursor", blob)
        self.assertNotIn("FakeConnection", blob)
        self.assertTrue(provider.calls)  # hops on the real file still happen
        tools = [c[0] for c in provider.calls]
        self.assertNotIn("query", tools)  # FakeCursor question was stripped
        self.assertEqual(len(out["validated_findings"]), 1)
        self.assertEqual(out["validated_findings"][0]["file"], LOADER)
        self.assertIsNone(out["validated_findings"][0].get("symbol"))

    def test_planner_asks_drop_fake_file(self):
        asks = deterministic_investigate_asks(FILES, DIFF)
        files = {a.file for a in asks}
        self.assertIn(LOADER, files)
        self.assertNotIn(WORDLIST, files)
        for a in asks:
            self.assertNotEqual(a.symbol, "FakeCursor")


class TestKeepAfterNeighbors(unittest.TestCase):
    def test_keep_and_attach_neighbor_snippet(self):
        provider = FakeProvider(neighbors_text="CALLS api.core.pipeline.run_loader")
        findings = [
            {
                "id": "corr-0",
                "title": "connect path may leak cursor",
                "claim": "SQLServerLoader.connect does not close the cursor on failure",
                "file": LOADER,
                "evidence": [LOADER],
                "symbol": "SQLServerLoader",
                "category": "correctness",
                "needs_investigation": True,
                "question": "who calls connect and is there a close/finally path?",
            }
        ]
        out = run_investigation(_state(findings), provider)
        self.assertFalse(out["investigation_report"]["skipped"])
        self.assertGreaterEqual(out["investigation_report"]["hops"], 1)
        kept = out["validated_findings"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["file"], LOADER)
        self.assertTrue(kept[0].get("evidence_ids"))
        self.assertTrue(kept[0].get("investigation_snippets"))
        self.assertIn("CALLS", " ".join(kept[0]["investigation_snippets"]))
        ok, reason = validate_finding(
            kept[0],
            files_changed=FILES,
            paths_in_diff=FILES,
            full_diff=DIFF,
        )
        self.assertTrue(ok, reason)
        self.assertEqual(out["hypotheses"][0]["status"], "confirmed")

    def test_empty_graphify_leaves_uncertain_does_not_invent(self):
        provider = FakeProvider(neighbors_text="")
        provider.get_node = lambda label: None  # type: ignore
        findings = [
            {
                "id": "corr-0",
                "title": "connect path",
                "file": LOADER,
                "evidence": [LOADER],
                "claim": "maybe leak",
                "needs_investigation": True,
            }
        ]
        # neighbors empty + node None → hops 0, status uncertain, finding still KEEP
        class EmptyProvider(FakeProvider):
            def get_node(self, label):
                self.calls.append(("get_node", label))
                return None

            def get_neighbors(self, label, relation_filter=None):
                self.calls.append(("get_neighbors", label))
                return NeighborResult(
                    node=GraphNode(id=label, label=label), raw_text=""
                )

            def query(self, question, depth=3):
                self.calls.append(("query", question))
                return KnowledgeQueryResult(question=question, raw_text="")

            def get_pr_impact(self, pr_number, repo=None):
                self.calls.append(("get_pr_impact", pr_number))
                return PRImpact(pr_number=pr_number, raw_text="")

        prov = EmptyProvider()
        out = run_investigation(_state(findings), prov)
        self.assertEqual(len(out["validated_findings"]), 1)
        self.assertEqual(out["hypotheses"][0]["status"], "uncertain")
        self.assertEqual(out["investigation_report"]["hops"], 0)


class TestInvestigateFileHelper(unittest.TestCase):
    def test_retriever_investigate_file_uses_provider(self):
        from core.graphify_retriever import GraphifyRetriever

        fake = FakeProvider()
        with patch(
            "core.graphify_retriever.graph_available", return_value=True
        ), patch(
            "core.graphify_retriever.get_knowledge_provider", return_value=fake
        ):
            r = GraphifyRetriever("FalkorDB/QueryWeaver")
            items = r.investigate_file(LOADER, symbol="SQLServerLoader")
        kinds = {i["kind"] for i in items}
        self.assertIn("node", kinds)
        self.assertIn("neighbors", kinds)
        tools = [c[0] for c in fake.calls]
        self.assertIn("get_node", tools)
        self.assertIn("get_neighbors", tools)
        self.assertNotIn("query", tools)


class TestGraphAndFinalPolicy(unittest.TestCase):
    def test_graph_has_investigate_between_validate_and_critic(self):
        from core.graph import build_review_graph

        g = build_review_graph()
        nodes = set(g.get_graph().nodes)
        self.assertIn("investigate", nodes)
        self.assertIn("validate_findings", nodes)
        self.assertIn("verify_findings", nodes)
        self.assertIn("critic_agent", nodes)

    def test_final_comment_when_empty_and_medium_risk(self):
        from core.agents import final_recommender
        from core.models import ReviewOutput

        captured = {}

        def fake_gen(**kwargs):
            captured["prompt"] = kwargs.get("prompt") or ""
            return ReviewOutput(
                summary="No validated findings.",
                recommendation="COMMENT",
                confidence=0.5,
            )

        state = {
            "validated_findings": [],
            "findings": [],
            "pr_understanding": {"summary": "loader", "risk_level": "low"},
            "review_plan": {"risk_level": "medium"},
            "hypotheses": [
                {
                    "id": "H1",
                    "status": "uncertain",
                    "claim": "could not confirm cursor close",
                    "file": LOADER,
                }
            ],
        }
        with patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            out = final_recommender(state)
        self.assertEqual(out["recommendation"], "COMMENT")
        self.assertIn("COMMENT", captured.get("prompt") or "")
        self.assertIn("could not confirm", captured.get("prompt") or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
