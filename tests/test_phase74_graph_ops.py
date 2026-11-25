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
from core.investigation.models import GraphOp
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
