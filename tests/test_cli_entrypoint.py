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


if __name__ == "__main__":
    unittest.main(verbosity=2)
