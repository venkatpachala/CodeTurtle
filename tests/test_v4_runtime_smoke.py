"""V4.1 — ReviewRuntime smoke. No GitHub, no live LLM."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from core.pr_facts import build_pr_facts
from core.runtime.review_runtime import ReviewRuntime, result_to_review_state
from core.review.contract import evaluate_policy

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
        expected = evaluate_policy(
            health=result.health, coverage=result.inspection, findings=result.findings,
            unresolved=result.unresolved, execution=result.execution,
            classification=str(facts.get("classification") or ""),
        )
        self.assertEqual(result.decision, expected.decision)
        self.assertEqual(result.policy_reason, expected.reasons[0])
        self.assertEqual(result.decision, "COMMENT")
        self.assertFalse(result.approval_eligible)
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

    def test_review_does_not_write_bundle_max_onto_settings(self):
        text = (ROOT / "cli" / "commands" / "review.py").read_text(encoding="utf-8")
        self.assertNotIn("settings.bundle_max", text)
        self.assertNotIn("settings.agent_max_steps", text)
        self.assertNotIn("settings.runtime =", text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
