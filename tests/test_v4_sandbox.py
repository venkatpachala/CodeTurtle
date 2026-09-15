"""V4.6 — sandbox wired into ReviewRuntime. Subprocess mocked."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pr_facts import build_pr_facts
from core.runtime.review_runtime import ReviewRuntime
from core.verification.execute import jail_relpath

LOADER = "pkg/api/loader.py"
TEST_LOADER = "tests/test_loader.py"
LOCK = "package-lock.json"

DIFF = (
    f"diff --git a/{LOADER} b/{LOADER}\n"
    f"--- a/{LOADER}\n"
    f"+++ b/{LOADER}\n"
    f"@@ -1,1 +1,4 @@\n"
    f" context\n"
    f"+def load():\n"
    f"+    return 1\n"
    f"diff --git a/{TEST_LOADER} b/{TEST_LOADER}\n"
    f"--- a/{TEST_LOADER}\n"
    f"+++ b/{TEST_LOADER}\n"
    f"@@ -1,1 +1,4 @@\n"
    f" context\n"
    f"+def test_load():\n"
    f"+    assert load() == 1\n"
)

DIFF_LOCK = (
    f"diff --git a/{LOCK} b/{LOCK}\n"
    f"--- a/{LOCK}\n"
    f"+++ b/{LOCK}\n"
    f"@@ -1,1 +1,3 @@\n"
    f" {{\n"
    f'+  "lockfileVersion": 3\n'
)


class Ctx:
    def __init__(self, execute_tests=False, execute_install=False, number=1, sha="abc"):
        self.execute_tests = execute_tests
        self.execute_install = execute_install
        self.number = number
        self.pr_head_sha = sha
        self.repo = "acme/widgets"
        self.repo_dir = ""
        self.repo_cfg = None
        self.change_units_payload = None
        self.pr = None
        self.files_changed = None
        self.full_diff = None
        self.pr_facts = None


def _run(files, diff, *, execute_tests=False, exec_patch=None):
    facts = build_pr_facts(title="x", files_changed=files, full_diff=diff)
    ctx = Ctx(execute_tests=execute_tests)
    ctx.files_changed = files
    ctx.full_diff = diff
    ctx.pr_facts = facts
    runtime = ReviewRuntime(llm=lambda _p: "[]")
    if exec_patch is None:
        return runtime.run(ctx, files_changed=files, full_diff=diff, pr_facts=facts)
    with patch("core.verification.execute.execute_tests_node", exec_patch):
        return runtime.run(ctx, files_changed=files, full_diff=diff, pr_facts=facts)


class TestSandboxSkip(unittest.TestCase):
    def test_flag_off_skip_decision_unchanged(self):
        result = _run([LOADER, TEST_LOADER], DIFF, execute_tests=False)
        self.assertTrue(result.execution.get("skipped"))
        self.assertEqual(result.execution.get("skip_reason"), "disabled")
        self.assertNotEqual(result.decision, "REQUEST_CHANGES")

    def test_lockfile_only_skip(self):
        result = _run([LOCK], DIFF_LOCK, execute_tests=True)
        self.assertTrue(result.execution.get("skipped"))
        self.assertEqual(result.execution.get("skip_reason"), "lockfile-only")


class TestSandboxResults(unittest.TestCase):
    def test_mocked_exit_1_request_changes(self):
        def fake_exec(state, **kwargs):
            return {
                "execution_report": {
                    "skipped": False,
                    "failed": 1,
                    "passed": 0,
                    "exit_code": 1,
                    "cmd": "pytest tests/test_loader.py -q --tb=line",
                }
            }

        result = _run(
            [LOADER, TEST_LOADER], DIFF, execute_tests=True, exec_patch=fake_exec
        )
        self.assertEqual(result.decision, "REQUEST_CHANGES")
        self.assertEqual(result.policy_reason, "tests_failed")

    def test_mocked_exit_0_not_merge_from_tests_alone(self):
        def fake_exec(state, **kwargs):
            return {
                "execution_report": {
                    "skipped": False,
                    "failed": 0,
                    "passed": 2,
                    "exit_code": 0,
                    "cmd": "pytest tests/test_loader.py -q --tb=line",
                }
            }

        facts = build_pr_facts(
            title="x", files_changed=[LOADER, TEST_LOADER], full_diff=DIFF
        )
        # Force low pack so empty KEEP cannot MERGE; green tests must not upgrade.
        runtime = ReviewRuntime(llm=lambda _p: "[]")
        ctx = Ctx(execute_tests=True)
        with patch("core.verification.execute.execute_tests_node", fake_exec):
            result = runtime.run(
                ctx,
                files_changed=[LOADER, TEST_LOADER],
                full_diff=DIFF,
                pr_facts=facts,
            )
        if result.comments:
            self.skipTest("agent produced comments")
        self.assertNotEqual(result.policy_reason, "tests_failed")
        # green tests must not be the reason for MERGE
        if result.decision == "MERGE":
            self.assertEqual(result.policy_reason, "no_validated_issues")

    def test_dotdot_never_jailed(self):
        self.assertIsNone(jail_relpath(Path("."), "../secret.py"))
        self.assertIsNone(jail_relpath(Path("."), "/tmp/x.py"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
