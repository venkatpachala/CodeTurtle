"""V4.2 — GraphContext + BundleAgent. LLM mocked."""

from __future__ import annotations

import json
import sys
import unittest
import tempfile
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
        self.assertTrue(is_valid_symbol("Foo.bar"))
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

    def test_candidate_prose_evidence_falls_back_to_changed_file(self):
        from core.agent.parse import candidate_dict

        parsed = candidate_dict({
            "file": LOADER,
            "claim": "load returns the wrong result",
            "evidence": "The changed code always returns a constant value.",
            "execution_path": "Loader.load(file)",
        }, bundle_id="B-001")
        self.assertEqual(parsed["evidence"], [LOADER])
        self.assertEqual(parsed["evidence_paths"], [LOADER])
        self.assertEqual(parsed["execution_path"], ["Loader.load"])


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
        self.assertEqual(self.tools.graph_callees("pkg/api/loader.py").get("error"), "invalid_symbol")

    def test_repository_search_fallback_without_graph(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir()
            (root / "caller.py").write_text("value = load()\n", encoding="utf-8")
            (root / "tests" / "test_load.py").write_text("def test_load(): load()\n", encoding="utf-8")
            tools = BundleTools(self.bundle, index=self.index, client=None, repo_dir=td)
            callers = tools.graph_callers("load")
            tests = tools.graph_tests("load")
            self.assertEqual(callers["source"], "repository_search")
            self.assertGreaterEqual(callers["n"], 2)
            self.assertEqual(tests["n"], 1)


class TestBundleAgentMocked(unittest.TestCase):
    def test_hypothesis_then_evidence_then_proof_candidate(self):
        discovery = {
            "hypotheses": [{
                "file": LOADER,
                "symbol": "load",
                "category": "correctness",
                "observation": "load now returns the constant 1",
                "hypothesis": "callers expecting loaded data receive the wrong value",
                "required_evidence": ["source", "callers", "tests"],
                "confidence": 0.6,
            }]
        }
        proof = [{
            "file": LOADER,
            "symbol": "load",
            "start_line": 2,
            "title": "load returns the wrong value",
            "claim": "load returns 1 instead of loaded data",
            "existing_code": "return 1",
            "invariant": "load returns repository data",
            "violating_condition": "every invocation returns the constant 1",
            "expected": "return loaded data",
            "actual": "returns 1",
            "execution_path": ["load"],
            "evidence": [LOADER],
            "severity": "medium",
            "confidence": 0.8,
        }]
        responses = [json.dumps(discovery), json.dumps(proof)]
        unit = {"id": "CU-001", "path": LOADER, "excerpt": "+def load():\n+    return 1\n", "symbols": ["load"]}
        bundle = Bundle(id="B-001", paths=[LOADER], units=[unit], symbols=["load"], kind="source")
        result = BundleAgent(llm=lambda _p: responses.pop(0)).run_result(
            bundle, BundleTools(bundle, index=build_diff_index(DIFF), client=None)
        )
        self.assertEqual(result.status, "VALID_CANDIDATES")
        self.assertEqual(len(result.hypotheses), 1)
        self.assertGreaterEqual(len(result.evidence_items), 1)
        self.assertEqual(result.stage_status["discovery"], "VALID_HYPOTHESES")
        self.assertEqual(result.candidates[0].file, LOADER)

    def test_run_result_distinguishes_invalid_json_from_healthy_empty(self):
        bundle = Bundle(id="B-001", paths=[LOADER], units=[], symbols=["load"], kind="source")
        invalid = BundleAgent(llm=lambda _p: "not JSON").run_result(bundle)
        empty = BundleAgent(llm=lambda _p: "[]").run_result(bundle)
        self.assertEqual(invalid.status, "INVALID_JSON")
        self.assertEqual(empty.status, "VALID_EMPTY")
        self.assertEqual(invalid.candidates, [])
        self.assertTrue(invalid.raw_outputs)

    def test_static_signal_seeds_investigation_when_model_discovers_none(self):
        proof = [{
            "file": LOADER, "symbol": "load", "start_line": 2,
            "title": "load returns a stale value", "claim": "load returns the changed constant",
            "existing_code": "return 1", "invariant": "load returns repository data",
            "violating_condition": "all calls return the constant", "expected": "loaded data",
            "actual": "1", "execution_path": ["load"], "evidence": [LOADER],
        }]
        bundle = Bundle(
            id="B-001", paths=[LOADER], units=[], symbols=["load"], kind="source",
            risk_signals=[{
                "kind": "stale_loop_state", "file": LOADER, "symbol": "load",
                "evidence": ["changed loop reads cached state"],
                "description": "A changed loop may use stale state.",
                "confidence": 0.8, "required_evidence": ["source"],
            }],
        )
        responses = ["[]", json.dumps(proof)]
        result = BundleAgent(llm=lambda _prompt: responses.pop(0)).run_result(
            bundle, BundleTools(bundle, index=build_diff_index(DIFF), client=None)
        )
        self.assertEqual(result.status, "VALID_CANDIDATES")
        self.assertEqual(result.hypotheses[0].id, "S-001")
        self.assertEqual(result.hypotheses[0].symbol, "load")

    def test_run_result_preserves_tool_history_and_max_steps(self):
        bundle = Bundle(id="B-001", paths=[LOADER], units=[], symbols=["load"], kind="source")
        agent = BundleAgent(
            llm=lambda _p: '{"tool":"read_hunk","path":"pkg/api/loader.py"}',
            max_steps=1,
        )
        out = agent.run_result(bundle, BundleTools(bundle, index=build_diff_index(DIFF), client=None))
        self.assertEqual(out.status, "MAX_STEPS")
        self.assertEqual(len(out.tool_calls), 1)

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
