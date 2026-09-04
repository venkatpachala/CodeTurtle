"""Phase 6.3a — GitHub Action contract tests. No live GitHub."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ci import (
    action_review_argv,
    ensure_session,
    resolve_github_token,
    should_skip_pr_review,
)

EXAMPLE = ROOT / "examples" / "github-action.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "codeturtle-review.yml"


class TestWorkflowFile(unittest.TestCase):
    def test_example_yaml_present(self):
        self.assertTrue(EXAMPLE.is_file(), "examples/github-action.yml missing")
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("pull_request:", text)
        self.assertIn("synchronize", text)
        self.assertIn("opened", text)
        self.assertIn("reopened", text)
        self.assertIn("pull-requests: write", text)
        self.assertIn("--comment", text)
        self.assertNotIn("ARGS+=(--execute-install)", text)
        self.assertIn("dependabot[bot]", text)

    def test_repo_workflow_present(self):
        self.assertTrue(WORKFLOW.is_file())
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("pull_request:", text)
        self.assertIn("synchronize", text)
        self.assertIn("pull-requests: write", text)
        self.assertIn("--comment", text)
        self.assertNotIn("ARGS+=(--execute-install)", text)


class TestSkipHelpers(unittest.TestCase):
    def test_dependabot_skip(self):
        skip, why = should_skip_pr_review(actor="dependabot[bot]", draft=False)
        self.assertTrue(skip)
        self.assertEqual(why, "dependabot")

    def test_human_actor_no_skip(self):
        skip, why = should_skip_pr_review(actor="alice", draft=False)
        self.assertFalse(skip)
        self.assertEqual(why, "")

    def test_draft_skip(self):
        skip, why = should_skip_pr_review(actor="alice", draft=True)
        self.assertTrue(skip)
        self.assertEqual(why, "draft")

    def test_draft_allowed(self):
        skip, why = should_skip_pr_review(
            actor="alice", draft=True, review_drafts=True
        )
        self.assertFalse(skip)
        self.assertEqual(why, "")


class TestSessionAndToken(unittest.TestCase):
    def test_ensure_session_creates_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".current_session"
            sid = ensure_session(str(p), create=lambda: "sess-ci-1")
            self.assertEqual(sid, "sess-ci-1")
            self.assertTrue(p.is_file())
            self.assertEqual(p.read_text(encoding="utf-8").strip(), "sess-ci-1")
            # second call reuses
            sid2 = ensure_session(str(p), create=lambda: "other")
            self.assertEqual(sid2, "sess-ci-1")

    def test_review_get_current_session_creates(self):
        from cli.commands.review import get_current_session

        with tempfile.TemporaryDirectory() as td:
            cwd = os.getcwd()
            try:
                os.chdir(td)
                with patch("core.memory.manager.init_db"):
                    with patch(
                        "core.memory.manager.MemoryManager.create_new_session",
                        return_value="auto-sess",
                    ):
                        sid = get_current_session()
                self.assertEqual(sid, "auto-sess")
                self.assertTrue(Path(".current_session").is_file())
            finally:
                os.chdir(cwd)

    def test_token_codeturtle_then_github(self):
        self.assertEqual(
            resolve_github_token(
                {"CODETURTLE_GITHUB_TOKEN": "pat-a", "GITHUB_TOKEN": "gha-b"}
            ),
            "pat-a",
        )
        self.assertEqual(
            resolve_github_token({"GITHUB_TOKEN": "gha-b"}),
            "gha-b",
        )
        self.assertEqual(
            resolve_github_token({}, fallback="from-settings"),
            "from-settings",
        )


class TestActionArgv(unittest.TestCase):
    def test_default_comment_no_execute_install(self):
        argv = action_review_argv("you/repo", 12)
        joined = " ".join(argv)
        self.assertIn("--comment", joined)
        self.assertNotIn("--execute-install", joined)
        self.assertNotIn("--execute-tests", joined)
        self.assertEqual(argv[4], "you/repo")
        self.assertEqual(argv[5], "12")

    def test_dry_run_flag(self):
        argv = action_review_argv("you/repo", 1, dry_run=True)
        self.assertIn("--dry-run", argv)
        self.assertNotIn("--comment", argv)


if __name__ == "__main__":
    unittest.main(verbosity=2)
