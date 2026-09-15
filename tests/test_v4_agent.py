"""V4.2 — GraphContext + BundleAgent. LLM mocked."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent.bundle_agent import BundleAgent
from core.agent.parse import parse_agent_output
from core.agent.tools import BundleTools
from core.graphctx.symbols import extract_identifiers, is_valid_symbol
from core.runtime.models import Bundle
from core.verification.diff_index import build_diff_index

LOADER = "pkg/api/loader.py"

DIFF = (
    f"diff --git a/{LOADER} b/{LOADER}\n"
    f"--- a/{LOADER}\n"
    f"+++ b/{LOADER}\n"
    f"@@ -1,1 +1,6 @@\n"
    f" context\n"
    f"+def load():\n"
    f"+    return 1\n"
    f"+class Loader:\n"
    f"+    pass\n"
)


class TestSymbols(unittest.TestCase):
    def test_extract_def_and_class(self):
        names = extract_identifiers(DIFF, LOADER)
        self.assertIn("load", names)
        self.assertIn("Loader", names)
        self.assertNotIn("py", names)

    def test_reject_path_and_py(self):
        self.assertFalse(is_valid_symbol("py"))
        self.assertFalse(is_valid_symbol("loader.py"))
        self.assertFalse(is_valid_symbol("pkg/api/loader.py"))
        self.assertFalse(is_valid_symbol("pkg.api.loader"))
        self.assertTrue(is_valid_symbol("load"))


class TestParse(unittest.TestCase):
    def test_list_ok(self):
        kind, data = parse_agent_output("[]")
        self.assertEqual(kind, "candidates")
        self.assertEqual(data, [])

    def test_invalid_json(self):
        kind, data = parse_agent_output("not json at all")
        self.assertEqual(kind, "invalid")
        self.assertIsNone(data)

    def test_tool_call(self):
        kind, data = parse_agent_output('{"tool":"read_hunk","path":"pkg/api/loader.py"}')
        self.assertEqual(kind, "tool")
        self.assertEqual(data["tool"], "read_hunk")


class TestTools(unittest.TestCase):
    def setUp(self):
        unit = {
            "id": "CU-001",
            "path": LOADER,
            "excerpt": "+def load():\n+    return 1\n",
            "symbols": ["load"],
            "kind": "source",
            "risk_hint": "none",
        }
        self.bundle = Bundle(id="B-001", paths=[LOADER], units=[unit], symbols=["load"], kind="source")
        self.index = build_diff_index(DIFF)
        self.tools = BundleTools(self.bundle, index=self.index, client=None)

    def test_read_hunk_in_bundle(self):
        out = self.tools.read_hunk(LOADER)
        self.assertNotIn("error", out)
        self.assertIn("load", out.get("text", ""))

    def test_read_hunk_rejects_outside_bundle(self):
        out = self.tools.read_hunk("pkg/cli/main.py")
        self.assertEqual(out.get("error"), "not_in_bundle")

    def test_graph_rejects_py_and_paths(self):
        self.assertEqual(self.tools.graph_node("py").get("error"), "invalid_symbol")
        self.assertEqual(self.tools.graph_callers("loader.py").get("error"), "invalid_symbol")
        self.assertEqual(self.tools.graph_tests("pkg/api/loader.py").get("error"), "invalid_symbol")


class TestBundleAgentMocked(unittest.TestCase):
    def test_invalid_json_no_candidates(self):
        bundle = Bundle(id="B-001", paths=[LOADER], units=[], symbols=["load"], kind="source")
        agent = BundleAgent(llm=lambda _p: "thanks I think this should MERGE")
        self.assertEqual(agent.run(bundle), [])

    def test_empty_list(self):
        bundle = Bundle(id="B-001", paths=[LOADER], units=[], symbols=["load"], kind="source")
        agent = BundleAgent(llm=lambda _p: "[]")
        self.assertEqual(agent.run(bundle), [])

    def test_parses_candidate_list(self):
        payload = [
            {
                "bundle_id": "B-001",
                "file": LOADER,
                "symbol": "load",
                "start_line": 2,
                "title": "load returns constant",
                "claim": "load always returns 1",
                "severity": "medium",
                "source": "agent",
                "evidence_paths": [LOADER],
            }
        ]
        bundle = Bundle(id="B-001", paths=[LOADER], units=[], symbols=["load"], kind="source")
        agent = BundleAgent(llm=lambda _p: json.dumps(payload))
        out = agent.run(bundle)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].file, LOADER)
        self.assertEqual(out[0].symbol, "load")

    def test_tool_then_candidates(self):
        responses = [
            '{"tool":"read_hunk","path":"pkg/api/loader.py"}',
            "[]",
        ]

        def llm(_prompt: str) -> str:
            return responses.pop(0)

        unit = {
            "id": "CU-001",
            "path": LOADER,
            "excerpt": "+def load():\n+    return 1\n",
            "symbols": ["load"],
        }
        bundle = Bundle(id="B-001", paths=[LOADER], units=[unit], symbols=["load"], kind="source")
        tools = BundleTools(bundle, index=build_diff_index(DIFF), client=None)
        agent = BundleAgent(llm=llm)
        self.assertEqual(agent.run(bundle, tools), [])
        self.assertEqual(responses, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
