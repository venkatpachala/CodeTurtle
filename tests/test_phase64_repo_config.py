"""Phase 6.4 — .codeturtle.yaml load, merge, ignore_paths. No live GitHub."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.output.publication import should_post
from core.ignore import filter_paths, is_ignored
from core.pr_facts import build_pr_facts
from core.repo_config import (
    RepoConfig,
    RepoConfigError,
    find_config_path,
    load_repo_config,
    merge_review_config,
    review_skip_reason,
    yaml_cannot_force_post,
)

SANITIZER = "api/sql_utils/sql_sanitizer.py"
LOCK = "package-lock.json"

class TestLoad(unittest.TestCase):
    def test_no_file_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(find_config_path(cwd=Path(td)))
            self.assertIsNone(load_repo_config(None))

    def test_extra_key_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".codeturtle.yaml"
            p.write_text("version: 1\nunknown_widget: true\ninline_max: 3\n", encoding="utf-8")
            cfg = load_repo_config(p)
            self.assertEqual(cfg.inline_max, 3)
            self.assertFalse(hasattr(cfg, "unknown_widget") and cfg.unknown_widget is True)

    def test_invalid_yaml_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".codeturtle.yaml"
            p.write_text("version: [\n", encoding="utf-8")
            with self.assertRaises(RepoConfigError):
                load_repo_config(p)

    def test_bad_type_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".codeturtle.yaml"
            p.write_text("inline_max: not-a-number\n", encoding="utf-8")
            with self.assertRaises(RepoConfigError):
                load_repo_config(p)

    def test_cli_config_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "custom.yaml"
            p.write_text("version: 1\ninline_max: 2\n", encoding="utf-8")
            found = find_config_path(str(p), cwd=Path(td))
            self.assertEqual(found, p)


class TestMerge(unittest.TestCase):
    def test_cli_execute_overrides_yaml_false(self):
        repo = RepoConfig(execute_tests=False, execute_install=False)
        s = MagicMock()
        s.inline_max = 8
        s.inline_lockfile = False
        s.execute_tests = False
        s.execute_install = False
        s.ollama_model = "qwen2.5-coder:7b"
        s.llm_backend = "ollama"
        eff = merge_review_config(
            repo=repo,
            cli_execute_tests=True,
            cli_execute_install=False,
            settings=s,
        )
        self.assertTrue(eff.execute_tests)

    def test_yaml_execute_true_without_flag(self):
        repo = RepoConfig(execute_tests=True)
        s = MagicMock()
        s.inline_max = 8
        s.inline_lockfile = False
        s.execute_tests = False
        s.execute_install = False
        s.ollama_model = "x"
        s.llm_backend = "ollama"
        eff = merge_review_config(repo=repo, cli_execute_tests=False, settings=s)
        self.assertTrue(eff.execute_tests)

    def test_yaml_bundle_and_step_limits(self):
        repo = RepoConfig(runtime="v4", bundle_max=2, agent_max_steps=3)
        s = MagicMock()
        s.inline_max = 8
        s.inline_lockfile = False
        s.execute_tests = False
        s.execute_install = False
        s.ollama_model = "x"
        s.llm_backend = "ollama"
        s.runtime = "v4"
        s.bundle_max = 4
        s.agent_max_steps = 4
        s.coverage_merge_min = 0.5
        eff = merge_review_config(repo=repo, settings=s)
        self.assertEqual(eff.bundle_max, 2)
        self.assertEqual(eff.agent_max_steps, 3)

    def test_no_repo_yaml_like_today(self):
        s = MagicMock()
        s.inline_max = 8
        s.inline_lockfile = False
        s.execute_tests = False
        s.execute_install = False
        s.ollama_model = "qwen2.5-coder:7b"
        s.llm_backend = "ollama"
        eff = merge_review_config(repo=None, cli_execute_tests=False, settings=s)
        self.assertFalse(eff.execute_tests)
        self.assertEqual(eff.ignore_paths, [])
        self.assertEqual(eff.inline_max, 8)


class TestSkipAndPost(unittest.TestCase):
    def test_skip_authors_match(self):
        from core.repo_config import EffectiveReviewConfig

        cfg = EffectiveReviewConfig(skip_authors=["dependabot[bot]", "renovate[bot]"])
        self.assertEqual(
            review_skip_reason(author="dependabot[bot]", draft=False, cfg=cfg),
            "skip_author",
        )
        self.assertIsNone(review_skip_reason(author="alice", draft=False, cfg=cfg))

    def test_dry_run_yaml_post_still_false(self):
        self.assertFalse(should_post(dry_run=True, comment=False))
        self.assertFalse(
            yaml_cannot_force_post(dry_run=True, comment=False, post_on_github=True)
        )


class TestIgnore(unittest.TestCase):
    def test_glob_md(self):
        pats = ["**/*.md"]
        self.assertTrue(is_ignored("README.md", pats))
        self.assertTrue(is_ignored("docs/a.md", pats))
        self.assertFalse(is_ignored(SANITIZER, pats))

    def test_ignore_lockfile_only_pr_empty(self):
        pats = ["**/package-lock.json"]
        kept = filter_paths([LOCK], pats)
        self.assertEqual(kept, [])
        facts = build_pr_facts(files_changed=kept, title="lock")
        self.assertNotEqual(facts["classification"], "lockfile-only")

    def test_ignore_md_keeps_source(self):
        pats = ["**/*.md"]
        kept = filter_paths([SANITIZER, "README.md", "docs/x.md"], pats)
        self.assertEqual(kept, [SANITIZER])
        facts = build_pr_facts(files_changed=kept)
        self.assertIn(SANITIZER, facts["files_changed"])
        self.assertEqual(facts["classification"], "source")


if __name__ == "__main__":
    unittest.main(verbosity=2)
