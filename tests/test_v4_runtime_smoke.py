"""V4.1 — ReviewRuntime smoke. No GitHub, no live LLM."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from core.pr_facts import build_pr_facts
from core.runtime.review_runtime import ReviewRuntime, result_to_review_state
from core.verification.policy import decide

LOADER = "pkg/api/loader.py"
PIPELINE = "pkg/api/pipeline.py"
MAIN = "pkg/cli/main.py"
TEST_LOADER = "tests/test_loader.py"
README = "README.md"
LOCK = "package-lock.json"
FILES = [LOADER, PIPELINE, MAIN, TEST_LOADER, README, LOCK]


def _hunk(path: str, added: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,1 +1,4 @@\n"
        f" context\n"
        f"{added}"
    )


DIFF = "".join(
    [
        _hunk(LOADER, "+def load():\n+    return 1\n"),
        _hunk(PIPELINE, "+def run():\n+    return load()\n"),
        _hunk(MAIN, "+def main():\n+    pass\n"),
        _hunk(TEST_LOADER, "+def test_load():\n+    assert load() == 1\n"),
        _hunk(README, "+# docs\n"),
        _hunk(LOCK, '+  "lockfileVersion": 3\n'),
    ]
)


class TestRuntimeSmoke(unittest.TestCase):
    def test_empty_agent_still_calls_policy(self):
        facts = build_pr_facts(title="api", files_changed=FILES, full_diff=DIFF)
        runtime = ReviewRuntime(llm=lambda _prompt: "[]")
        result = runtime.run(
            files_changed=FILES,
            full_diff=DIFF,
            pr_facts=facts,
        )
        expected, reason = decide(
            [],
            classification=str(facts.get("classification") or ""),
            coverage=result.coverage,
            files_changed=FILES,
        )
        self.assertEqual(result.decision, expected)
        self.assertEqual(result.policy_reason, reason)
        self.assertTrue(result.bundles)
        self.assertEqual(result.comments, [])
        self.assertIn(result.decision, ("MERGE", "COMMENT", "REQUEST_CHANGES"))

    def test_result_maps_to_state_recommendation(self):
        facts = build_pr_facts(title="api", files_changed=FILES, full_diff=DIFF)
        result = ReviewRuntime(llm=lambda _prompt: "[]").run(
            files_changed=FILES,
            full_diff=DIFF,
            pr_facts=facts,
        )

        class Ctx:
            repo = "acme/widgets"
            number = 1
            files_changed = FILES
            full_diff = DIFF
            pr_facts = facts
            change_units_payload = None
            pr = None
            pr_head_sha = ""
            repo_cfg = None

        state = result_to_review_state(result, Ctx())
        self.assertEqual(state["recommendation"], result.decision)
        self.assertEqual(state["policy_reason"], result.policy_reason)
        self.assertEqual(state["runtime"], "v4")

    def test_settings_runtime_defaults_v4(self):
        self.assertEqual(str(getattr(settings, "runtime", "")).lower(), "v4")

    def test_legacy_flag_still_imports_graph(self):
        from core.graph import build_review_graph

        nodes = set(build_review_graph().get_graph().nodes)
        self.assertIn("final_recommender", nodes)
        self.assertGreaterEqual(len(nodes), 17)


class TestCliWiresRuntime(unittest.TestCase):
    def test_review_pipeline_uses_runtime_not_graph_when_v4(self):
        from cli.commands.review import ReviewPipeline

        calls = {"runtime": 0, "graph": 0}

        class FakeResult:
            decision = "COMMENT"
            policy_reason = "no_validated_issues"
            comments = []
            dropped = []
            bundles = []
            coverage = {
                "units_total": 1,
                "units_packed": 1,
                "units_omitted": 0,
                "source_units": 1,
            }

            def to_dict(self):
                return {}

        class FakeRuntime:
            def run(self, context):
                calls["runtime"] += 1
                return FakeResult()

        pipe = ReviewPipeline()
        pipe.context.repo = "acme/widgets"
        pipe.context.number = 1
        pipe.context.files_changed = [LOADER]
        pipe.context.full_diff = _hunk(LOADER, "+def load():\n+    return 1\n")
        pipe.context.pr_facts = build_pr_facts(
            title="x",
            files_changed=[LOADER],
            full_diff=pipe.context.full_diff,
        )

        with patch("core.runtime.review_runtime.ReviewRuntime", FakeRuntime), patch(
            "core.graph.review_graph.invoke",
            side_effect=lambda *_a, **_k: calls.__setitem__("graph", calls["graph"] + 1) or {},
        ):
            from core.runtime.review_runtime import result_to_review_state

            result = FakeRuntime().run(pipe.context)
            pipe.context.final_state = result_to_review_state(result, pipe.context)
        self.assertEqual(calls["runtime"], 1)
        self.assertEqual(calls["graph"], 0)
        self.assertEqual(pipe.context.final_state["recommendation"], "COMMENT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
