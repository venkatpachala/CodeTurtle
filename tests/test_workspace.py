"""Auto clone + Graphify index. Clone/graphify are mocked — no network."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Proc:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class TestReposHome(unittest.TestCase):
    def test_resolve_graph_path_uses_codeturtle_home_repos(self):
        from core.repository_knowledge.paths import resolve_graph_path, resolve_repo_dir

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            with patch.dict(
                os.environ,
                {"CODETURTLE_HOME": str(home), "CODETURTLE_REPOS_ROOT": ""},
                clear=False,
            ):
                os.environ.pop("CODETURTLE_REPOS_ROOT", None)
                repo_dir = resolve_repo_dir("confident-ai/deepeval")
                graph = resolve_graph_path("confident-ai/deepeval")
        self.assertEqual(repo_dir, (home / "repos" / "confident-ai_deepeval"))
        self.assertTrue(
            str(graph).replace("\\", "/").endswith(
                "repos/confident-ai_deepeval/graphify-out/graph.json"
            )
        )


class TestEnsureClone(unittest.TestCase):
    def test_clone_invoked_when_missing(self):
        from core.workspace import ensure_clone

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            calls = []

            def run(argv, **kwargs):
                calls.append(list(argv))
                dest = Path(argv[-1])
                dest.mkdir(parents=True, exist_ok=True)
                (dest / ".git").mkdir()
                return _Proc()

            with patch.dict(os.environ, {"CODETURTLE_HOME": str(home)}, clear=False):
                os.environ.pop("CODETURTLE_REPOS_ROOT", None)
                dest = ensure_clone("confident-ai/deepeval", run=run)
            self.assertTrue((dest / ".git").is_dir())
            self.assertEqual(calls[0][:3], ["git", "clone", "--depth"])
            self.assertIn("https://github.com/confident-ai/deepeval.git", calls[0])

    def test_clone_skipped_when_git_dir_exists(self):
        from core.workspace import ensure_clone

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            dest = home / "repos" / "owner_repo"
            dest.mkdir(parents=True)
            (dest / ".git").mkdir()
            run = MagicMock(side_effect=AssertionError("clone should not run"))
            with patch.dict(os.environ, {"CODETURTLE_HOME": str(home)}, clear=False):
                os.environ.pop("CODETURTLE_REPOS_ROOT", None)
                out = ensure_clone("owner/repo", run=run)
            self.assertEqual(out, dest)
            run.assert_not_called()


class TestEnsureIndex(unittest.TestCase):
    def test_graphify_extract_when_graph_missing(self):
        from core.workspace import ensure_index

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            dest = home / "repos" / "owner_repo"
            dest.mkdir(parents=True)
            (dest / ".git").mkdir()

            def run(argv, **kwargs):
                if argv[:1] == ["git"]:
                    return _Proc(stdout="abc123\n")
                graph = dest / "graphify-out" / "graph.json"
                graph.parent.mkdir(parents=True, exist_ok=True)
                graph.write_text("{}", encoding="utf-8")
                return _Proc()

            with patch.dict(os.environ, {"CODETURTLE_HOME": str(home)}, clear=False):
                os.environ.pop("CODETURTLE_REPOS_ROOT", None)
                graph = ensure_index("owner/repo", run=run)
            self.assertTrue(graph.is_file())
            self.assertEqual(graph.name, "graph.json")

    def test_graphify_skipped_when_fresh(self):
        from core.workspace import ensure_index

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            dest = home / "repos" / "owner_repo"
            gdir = dest / "graphify-out"
            gdir.mkdir(parents=True)
            (dest / ".git").mkdir()
            (gdir / "graph.json").write_text("{}", encoding="utf-8")
            (gdir / ".codeturtle-rev").write_text("abc123\n", encoding="utf-8")

            def run(argv, **kwargs):
                if argv[:1] == ["git"] and "rev-parse" in argv:
                    return _Proc(stdout="abc123\n")
                raise AssertionError(f"unexpected {argv}")

            with patch.dict(os.environ, {"CODETURTLE_HOME": str(home)}, clear=False):
                os.environ.pop("CODETURTLE_REPOS_ROOT", None)
                graph = ensure_index("owner/repo", run=run)
            self.assertTrue(graph.is_file())


class TestUserConfig(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        from core.user_config import load_user_config, save_user_config

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.toml"
            save_user_config(
                {
                    "github_token": "gho_test",
                    "ollama_model": "qwen2.5:7b",
                    "llm_backend": "ollama",
                },
                path=path,
            )
            data = load_user_config(path)
            self.assertEqual(data["github_token"], "gho_test")
            self.assertEqual(data["ollama_model"], "qwen2.5:7b")
            self.assertEqual(data["llm_backend"], "ollama")

    def test_toml_applied_before_missing_env(self):
        from core.user_config import apply_user_config_to_environ

        env = {}
        apply_user_config_to_environ(
            {"github_token": "from-toml", "ollama_model": "qwen2.5:7b"},
            environ=env,
        )
        self.assertEqual(env["GITHUB_TOKEN"], "from-toml")
        self.assertEqual(env["OLLAMA_MODEL"], "qwen2.5:7b")
        env2 = {"GITHUB_TOKEN": "already"}
        apply_user_config_to_environ({"github_token": "from-toml"}, environ=env2)
        self.assertEqual(env2["GITHUB_TOKEN"], "already")

    def test_detect_prefers_env_over_gh(self):
        from core.user_config import detect_github_token

        tok = detect_github_token(
            environ={"GITHUB_TOKEN": "env-token"},
            gh_token="gh-token",
        )
        self.assertEqual(tok, "env-token")


class TestOllamaList(unittest.TestCase):
    def test_parses_ollama_list_table(self):
        from cli.commands.wizard import list_ollama_models

        fake = (
            "NAME                       ID              SIZE      MODIFIED\n"
            "qwen2.5:7b                 abc             4.7 GB    5 weeks ago\n"
            "llama3.2:latest            def             2.0 GB    1 day ago\n"
        )

        def fake_run(argv, **kwargs):
            self.assertEqual(argv[:2], ["ollama", "list"])
            p = _Proc(stdout=fake, returncode=0)
            return p

        with patch("cli.commands.wizard.subprocess.run", side_effect=fake_run):
            names = list_ollama_models()
        self.assertEqual(names, ["qwen2.5:7b", "llama3.2:latest"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
