"""Unmocked CLI entrypoint tests. Real Typer app, real subprocess."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "cli.main", *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
        timeout=timeout,
    )


class TestCliHelp(unittest.TestCase):
    def test_no_args_noninteractive_does_not_hang(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["CODETURTLE_NO_WIZARD"] = "1"
        proc = subprocess.run(
            [sys.executable, "-m", "cli.main"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=env,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        blob = ((proc.stdout or "") + (proc.stderr or "")).lower()
        self.assertIn("review", blob)

    def test_root_help_lists_commands(self):
        proc = _run("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        blob = (proc.stdout or "") + (proc.stderr or "")
        for name in ("review", "add-repo", "new-session", "graphify-test"):
            self.assertIn(name, blob)

    def test_review_help_defaults_dry_run(self):
        proc = _run("review", "--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        blob = (proc.stdout or "") + (proc.stderr or "")
        self.assertIn("--dry-run", blob)
        self.assertIn("--comment", blob)


class TestObservabilityLogger(unittest.TestCase):
    def test_info_accepts_structlog_kwargs(self):
        from core.observability import get_logger

        get_logger().info("Starting review", repo="confident-ai/deepeval", pr_number=3288)


class TestHelpImportIsolation(unittest.TestCase):
    def test_cli_main_does_not_import_optional_backends(self):
        script = (
            "import sys, cli.main\n"
            "missing = [n for n in ('qdrant_client', 'neo4j', 'langfuse', "
            "'langchain_qdrant') if n in sys.modules]\n"
            "raise SystemExit(0 if not missing else 'imported: ' + ','.join(missing))\n"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=env,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class TestOllamaModelSource(unittest.TestCase):
    def test_process_env_beats_settings(self):
        from cli.commands.review import _ollama_model_and_source

        old = os.environ.get("OLLAMA_MODEL")
        os.environ["OLLAMA_MODEL"] = "openbmb/minicpm5-2b"
        try:
            model, source = _ollama_model_and_source()
        finally:
            if old is None:
                os.environ.pop("OLLAMA_MODEL", None)
            else:
                os.environ["OLLAMA_MODEL"] = old
        self.assertEqual(model, "openbmb/minicpm5-2b")
        self.assertEqual(source, "env OLLAMA_MODEL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
