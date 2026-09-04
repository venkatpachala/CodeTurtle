"""Phase 7.4 — typed Graphify asks (find_callers / find_callees / find_tests)."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.investigation.graphify_ops import run_op
from core.investigation.loop import run_investigation
from core.investigation.models import GraphOp, Hypothesis, InvestigationAsk
from core.investigation.planner import (
    MAX_GRAPHIFY_CALLS_IN_INVESTIGATE,
    plan_graphify_calls,
    plan_typed_asks,
)
from core.pr_facts import build_pr_facts
from core.repository_knowledge.models import (
    GraphNode,
    KnowledgeQueryResult,
    NeighborResult,
    PRImpact,
)

LOADER = "api/loaders/sqlserver_loader.py"
SCHEMA = "api/core/schema_loader.py"
PIPELINE = "api/core/pipeline.py"
WORDLIST = ".github/wordlist.txt"
LOCK = "package-lock.json"

DIFF = f"""diff --git a/{LOADER} b/{LOADER}
--- a/{LOADER}
+++ b/{LOADER}
@@ -1,3 +1,10 @@
 class SQLServerLoader:
     def load_schema(self):
         pass
+    def refresh_graph_schema(self):
+        self.graph.delete(node)
+        return True
"""
FILES = [LOADER, SCHEMA, PIPELINE, WORDLIST]


class FakeGraphify:
    """Records (op, symbol). Optional canned neighbors / empty typed ops."""

    def __init__(self, callers_text="DEFINED_IN api/loaders/sqlserver_loader.py\nA\nB\nC"):
        self.ops: list[tuple] = []
        self.calls: list[tuple] = []
        self.callers_text = callers_text
        self.callees_text = "calls graph.delete"
        self.tests_text = ""
        self.neighbors_text = "CALLS pipeline.load"
        self.empty_typed = False

    def find_callers(self, symbol):
        self.ops.append(("find_callers", symbol))
        self.calls.append(("find_callers", symbol))
        text = "" if self.empty_typed else self.callers_text
        return NeighborResult(node=GraphNode(id=symbol, label=symbol), raw_text=text)

    def find_callees(self, symbol):
        self.ops.append(("find_callees", symbol))
        self.calls.append(("find_callees", symbol))
        text = "" if self.empty_typed else self.callees_text
        return NeighborResult(node=GraphNode(id=symbol, label=symbol), raw_text=text)

    def find_tests(self, target):
        self.ops.append(("find_tests", target))
        self.calls.append(("find_tests", target))
        return KnowledgeQueryResult(question=f"tests for {target}", raw_text=self.tests_text)

    def get_node(self, label):
        self.ops.append(("get_node", label))
        self.calls.append(("get_node", label))
        return GraphNode(id=label, label=label, raw={"text": f"node {label} path={LOADER}"})

    def get_neighbors(self, label, relation_filter=None):
        self.ops.append(("get_neighbors", label))
        self.calls.append(("get_neighbors", label))
        return NeighborResult(
            node=GraphNode(id=label, label=label),
            raw_text=self.neighbors_text,
        )

    def query(self, question, depth=3):
        self.ops.append(("query", question))
        self.calls.append(("query", question))
        return KnowledgeQueryResult(question=question, raw_text=f"query:{question}")

    def get_pr_impact(self, pr_number, repo=None):
        self.ops.append(("pr_impact", pr_number))
        self.calls.append(("get_pr_impact", pr_number))
        return PRImpact(pr_number=pr_number, repo=repo, raw_text="impact ok")


def _facts():
    return build_pr_facts(
        title="SQL Server loader",
        files_changed=FILES,
        full_diff=DIFF,
        pr_number=538,
        repo="FalkorDB/QueryWeaver",
    )


def _state(findings, extra=None):
    st = {
        "repo": "FalkorDB/QueryWeaver",
        "number": 538,
        "title": "SQL Server loader",
        "files_changed": FILES,
        "full_diff": DIFF,
        "pr_facts": _facts(),
        "validated_findings": findings,
        "findings": findings,
        "classified_findings": findings,
        "hypothesis_pool": [
            f
            for f in findings
            if str(f.get("hypothesis_status") or "KEEP") in ("KEEP", "PLAUSIBLE")
        ],
        "review_plan": {"investigate": []},
    }
    if extra:
        st.update(extra)
    return st


def _hyp_refresh(**kwargs):
    d = {
        "id": "p-1",
        "title": "schema refresh may fail",
        "claim": "refresh_graph_schema can raise on empty catalog",
        "file": "",
        "evidence": [],
        "symbol": "refresh_graph_schema",
        "hypothesis_status": "PLAUSIBLE",
        "risk_hint": "mutation",
    }
    d.update(kwargs)
    return d


class TestRunOp(unittest.TestCase):
    def test_run_op_records_find_callers(self):
        fake = FakeGraphify()
        items = run_op(fake, GraphOp.FIND_CALLERS, symbol="refresh_graph_schema", path=LOADER)
        self.assertTrue(items)
        self.assertIn(("find_callers", "refresh_graph_schema"), fake.ops)
        self.assertTrue(any(i.kind == "callers" for i in items))
        self.assertNotIn("get_neighbors", [o[0] for o in fake.ops])

    def test_run_op_lockfile_skipped(self):
        fake = FakeGraphify()
        items = run_op(
            fake, GraphOp.FIND_CALLERS, symbol="pkg", path=LOCK
        )
        self.assertEqual(items, [])
        self.assertEqual(fake.ops, [])

    def test_run_op_error_returns_empty(self):
        class Boom:
            def find_callers(self, symbol):
                raise RuntimeError("mcp down")

        self.assertEqual(
            run_op(Boom(), GraphOp.FIND_CALLERS, symbol="refresh_graph_schema"),
            [],
        )


class TestPlannerTypedAsks(unittest.TestCase):
    def test_symbol_hyp_includes_find_callers_and_get_node(self):
        h = Hypothesis(
            id="H1",
            claim="refresh_graph_schema can raise",
            title="schema refresh may fail",
            symbol="refresh_graph_schema",
            file="",
            file_hint=LOADER,
            hypothesis_kind="PLAUSIBLE",
            risk_hint="mutation",
        )
        asks = plan_typed_asks([h], pr_number=538, repo="FalkorDB/QueryWeaver")
        ops = [a.op for a in asks if a.hypothesis_id == "H1"]
        self.assertIn(GraphOp.GET_NODE, ops)
        self.assertIn(GraphOp.FIND_CALLERS, ops)
        self.assertEqual(ops[0], GraphOp.GET_NODE)
        self.assertIn(GraphOp.FIND_CALLERS, ops[:3])
        self.assertIn(GraphOp.FIND_CALLEES, ops)  # refresh/mutation
        self.assertEqual(sum(1 for a in asks if a.op == GraphOp.PR_IMPACT), 1)
        self.assertNotIn(GraphOp.GET_NEIGHBORS, ops)

    def test_plan_graphify_calls_sets_op(self):
        h = Hypothesis(
            id="H1",
            claim="refresh_graph_schema can raise",
            symbol="refresh_graph_schema",
            file=LOADER,
            hypothesis_kind="KEEP",
        )
        calls = plan_graphify_calls([h], pr_number=538)
        self.assertTrue(any(c.op == "find_callers" and c.symbol == "refresh_graph_schema" for c in calls))
        self.assertTrue(any(c.tool == "get_node" and "refresh_graph_schema" in (c.label or "") for c in calls))

    def test_lockfile_path_never_find_callers(self):
        h = Hypothesis(
            id="H1",
            claim="lock bump",
            file=LOCK,
            symbol="version",
            hypothesis_kind="KEEP",
        )
        asks = plan_typed_asks([h], pr_number=571)
        self.assertFalse(any(a.op == GraphOp.FIND_CALLERS for a in asks))
        self.assertFalse(any(a.file == LOCK and a.op != GraphOp.PR_IMPACT for a in asks))


class TestLoopDispatch(unittest.TestCase):
    def test_investigate_emits_find_callers_not_only_neighbors(self):
        fake = FakeGraphify()
        findings = [_hyp_refresh()]
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = run_investigation(_state(findings), fake)
        self.assertFalse(out["investigation_report"]["skipped"])
        ops = [a["op"] for a in out["investigation_report"]["asks"]]
        self.assertIn("find_callers", ops)
        self.assertIn("get_node", ops)
        self.assertIn(("find_callers", "refresh_graph_schema"), fake.ops)
        log = buf.getvalue()
        self.assertIn("ask=find_callers", log)
        self.assertIn("symbol=refresh_graph_schema", log)
        self.assertIn("callers=", log)

    def test_callers_promote_plausible_to_keep(self):
        fake = FakeGraphify(callers_text=f"DEFINED_IN {LOADER} refresh_graph_schema")
        findings = [_hyp_refresh()]
        out = run_investigation(_state(findings), fake)
        promoted = [f for f in out["classified_findings"] if f.get("id") == "p-1"]
        self.assertEqual(promoted[0]["hypothesis_status"], "KEEP")
        self.assertEqual(promoted[0]["file"], LOADER)
        self.assertTrue(out["validated_findings"])

    def test_empty_callers_fallback_neighbors_under_budget(self):
        fake = FakeGraphify()
        fake.empty_typed = True
        fake.tests_text = ""
        findings = [
            {
                "id": "k-1",
                "title": "connect path",
                "claim": "SQLServerLoader.connect may leak",
                "file": LOADER,
                "evidence": [LOADER],
                "symbol": "SQLServerLoader",
                "hypothesis_status": "KEEP",
                "needs_investigation": True,
            }
        ]
        out = run_investigation(_state(findings), fake)
        ops = [a["op"] for a in out["investigation_report"]["asks"]]
        self.assertIn("find_callers", ops)
        self.assertIn("get_neighbors", ops)
        self.assertLessEqual(out["investigation_report"]["calls"], MAX_GRAPHIFY_CALLS_IN_INVESTIGATE)
        self.assertIn(("get_neighbors", "SQLServerLoader"), fake.ops)

    def test_pr_impact_at_most_once_with_three_hyps(self):
        fake = FakeGraphify()
        findings = [
            {
                "id": f"k-{i}",
                "title": f"claim {name}",
                "claim": f"check {name}",
                "file": name,
                "evidence": [name],
                "symbol": "SQLServerLoader",
                "hypothesis_status": "KEEP",
                "needs_investigation": True,
            }
            for i, name in enumerate([LOADER, SCHEMA, PIPELINE])
        ]
        out = run_investigation(_state(findings), fake)
        n_impact = sum(1 for c in fake.calls if c[0] == "get_pr_impact")
        self.assertLessEqual(n_impact, 1)
        self.assertLessEqual(out["investigation_report"]["calls"], MAX_GRAPHIFY_CALLS_IN_INVESTIGATE)
        self.assertLessEqual(len(out["hypotheses"]), 3)

    def test_budget_seventh_op_not_sent(self):
        fake = FakeGraphify()
        findings = [
            {
                "id": f"k-{i}",
                "title": f"claim {name}",
                "claim": f"refresh fail in {name}",
                "file": name,
                "evidence": [name],
                "symbol": "refresh_graph_schema",
                "hypothesis_status": "KEEP",
                "needs_investigation": True,
                "risk_hint": "mutation",
            }
            for i, name in enumerate([LOADER, SCHEMA, PIPELINE])
        ]
        out = run_investigation(_state(findings), fake)
        self.assertLessEqual(len(fake.calls), MAX_GRAPHIFY_CALLS_IN_INVESTIGATE)
        self.assertLessEqual(out["investigation_report"]["calls"], 6)
        self.assertLessEqual(len(out["investigation_report"]["asks"]), 6)

    def test_wordlist_rejected_zero_calls(self):
        fake = FakeGraphify()
        findings = [
            {
                "id": "w-1",
                "title": "Naming and Documentation",
                "claim": "wordlist nit",
                "file": WORDLIST,
                "evidence": [WORDLIST],
                "hypothesis_status": "REJECTED",
            }
        ]
        out = run_investigation(_state(findings), fake)
        self.assertTrue(out["investigation_report"]["skipped"])
        self.assertEqual(fake.calls, [])
        self.assertEqual(fake.ops, [])

    def test_571_lockfile_skip_zero_typed_asks(self):
        fake = FakeGraphify()
        facts = build_pr_facts(files_changed=[LOCK], full_diff="", pr_number=571, title="lock")
        out = run_investigation(
            {
                "repo": "FalkorDB/QueryWeaver",
                "number": 571,
                "files_changed": [LOCK],
                "full_diff": "",
                "pr_facts": facts,
                "classified_findings": [_hyp_refresh()],
                "hypothesis_pool": [_hyp_refresh()],
                "validated_findings": [],
                "review_plan": {"investigate": [InvestigationAsk(file=LOCK, ask="find_callers")]},
            },
            fake,
        )
        self.assertTrue(out["investigation_report"]["skipped"])
        self.assertEqual(out["investigation_report"]["reason"], "no_changed_path_hypotheses")
        self.assertEqual(fake.ops, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
