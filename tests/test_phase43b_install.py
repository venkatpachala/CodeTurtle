"""Phase 4.3b — opt-in uv/venv install before pytest. Subprocess is mocked."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.verification.execute import (
    detect_python_manifest,
    execute_tests_node,
    jail_relpath,
)

SANITIZER = "api/sql_utils/sql_sanitizer.py"
TEST_SAN = "tests/test_sql_sanitizer.py"
LOCK = "package-lock.json"


class FakeProc:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


def _which_map(**mapping):
    def which(name):
        return mapping.get(name)
    return which


class TestInstallGates(unittest.TestCase):
    def test_flag_off_no_uv_pip_pytest(self):
        calls = []

        def runner(*a, **k):
            calls.append(a)
            raise AssertionError("subprocess must not run")

        with patch("core.verification.execute.settings") as s:
            s.execute_tests = False
            s.execute_install = True
            s.execute_timeout_s = 120
            s.execute_max_files = 8
            s.execute_install_timeout_s = 180
            with patch.dict("os.environ", {"CODETURTLE_EXECUTE_TESTS": ""}, clear=False):
                out = execute_tests_node(
                    {
                        "execute_tests": False,
                        "execute_install": True,
                        "pr_facts": {"classification": "source", "files_changed": [SANITIZER]},
                        "files_changed": [SANITIZER],
                        "validated_findings": [],
                    },
                    runner=runner,
                )
        self.assertEqual(out["execution_report"]["skip_reason"], "disabled")
        self.assertEqual(calls, [])

    def test_execute_tests_no_install_import_fail(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(list(cmd))
            joined = " ".join(str(c) for c in cmd)
            if "pytest" in joined:
                return FakeProc(1, "", "ModuleNotFoundError: No module named 'queryweaver'\n")
            return FakeProc(0, "")

        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            (dest_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            (dest_path / "uv.lock").write_text("lock", encoding="utf-8")
            tests = dest_path / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_sql_sanitizer.py").write_text("x", encoding="utf-8")
            return True, ""

        out = execute_tests_node(
            {
                "execute_tests": True,
                "execute_install": False,
                "repo": "FalkorDB/QueryWeaver",
                "number": 538,
                "pr_head_sha": "abc",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [SANITIZER, TEST_SAN],
                    "source_files": [SANITIZER],
                },
                "validated_findings": [
                    {"file": SANITIZER, "related_tests": [TEST_SAN], "verification_status": "supported"}
                ],
            },
            runner=runner,
            checkout=fake_checkout,
            which=_which_map(pytest="pytest", uv="uv"),
        )
        self.assertEqual(out["execution_report"]["skip_reason"], "deps_missing")
        uv_cmds = [c for c in calls if c and str(c[0]) == "uv"]
        self.assertEqual(uv_cmds, [])

    def test_lockfile_only_both_flags(self):
        calls = []

        def runner(*a, **k):
            calls.append(a)
            raise AssertionError("no subprocess on lockfile PR")

        out = execute_tests_node(
            {
                "execute_tests": True,
                "execute_install": True,
                "pr_facts": {
                    "classification": "lockfile-only",
                    "files_changed": [LOCK],
                    "source_files": [],
                },
                "files_changed": [LOCK],
                "validated_findings": [{"file": LOCK, "related_tests": []}],
            },
            runner=runner,
        )
        self.assertEqual(out["execution_report"]["skip_reason"], "lockfile-only")
        self.assertEqual(calls, [])


class TestUvSync(unittest.TestCase):
    def _checkout_uv(self, dest_path):
        dest_path.mkdir(parents=True, exist_ok=True)
        (dest_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (dest_path / "uv.lock").write_text("frozen-lock", encoding="utf-8")
        (dest_path / "pyproject.toml").write_text(
            '[project]\nname = "queryweaver"\n[tool.pytest.ini_options]\n',
            encoding="utf-8",
        )
        tests = dest_path / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_sql_sanitizer.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        return True, ""

    def test_uv_lock_sync_frozen_then_pytest(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(list(cmd))
            joined = " ".join(str(c) for c in cmd)
            self.assertNotEqual(kwargs.get("shell"), True)
            if "sync" in joined:
                return FakeProc(0, "synced\n")
            if "pytest" in joined:
                return FakeProc(0, "12 passed\n")
            return FakeProc(0, "")

        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            return self._checkout_uv(dest_path)

        findings = [
            {
                "file": SANITIZER,
                "related_tests": [TEST_SAN],
                "verification_status": "supported",
                "severity": "concern",
                "title": "quoter",
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            missing_clone = Path(td) / "no-clone"
            with patch(
                "core.verification.execute.resolve_repo_dir",
                return_value=missing_clone,
            ):
                out = execute_tests_node(
                    {
                        "execute_tests": True,
                        "execute_install": True,
                        "repo": "FalkorDB/QueryWeaver",
                        "number": 538,
                        "pr_head_sha": "abc",
                        "pr_facts": {
                            "classification": "source",
                            "files_changed": [SANITIZER, TEST_SAN],
                            "source_files": [SANITIZER],
                        },
                        "validated_findings": findings,
                    },
                    runner=runner,
                    checkout=fake_checkout,
                    which=_which_map(uv="uv", pytest="pytest"),
                )
        self.assertFalse(out["execution_report"]["skipped"])
        self.assertEqual(out["execution_report"]["python_env"], "uv_sync")
        self.assertTrue(out["execution_report"]["python"]["frozen"])
        sync = [c for c in calls if c[:2] == ["uv", "sync"]]
        self.assertTrue(sync)
        self.assertIn("--frozen", sync[0])
        pytest_cmds = [c for c in calls if "pytest" in c]
        self.assertTrue(pytest_cmds)
        self.assertEqual(pytest_cmds[0][:3], ["uv", "run", "--frozen"])
        self.assertIn(TEST_SAN, pytest_cmds[0])
        self.assertEqual(out["validated_findings"][0]["verification_status"], "supported")
        self.assertTrue(out["validated_findings"][0]["tests_passed"])

    def test_uv_sync_exit_1_no_pytest(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["uv", "sync"]:
                return FakeProc(1, "", "lock out of date")
            if "pytest" in cmd:
                raise AssertionError("pytest must not run after install_failed")
            return FakeProc(0, "")

        out = execute_tests_node(
            {
                "execute_tests": True,
                "execute_install": True,
                "repo": "x/y",
                "number": 9,
                "pr_head_sha": "sha",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [SANITIZER, TEST_SAN],
                    "source_files": [SANITIZER],
                },
                "validated_findings": [{"file": SANITIZER, "related_tests": [TEST_SAN]}],
            },
            runner=runner,
            checkout=lambda repo_dir, sha, dest_path, runner=None: self._checkout_uv(dest_path),
            which=_which_map(uv="uv", pytest="pytest"),
        )
        self.assertEqual(out["execution_report"]["skip_reason"], "install_failed")
        self.assertTrue(out["execution_report"]["skipped"])
        self.assertFalse(any("pytest" in c for c in calls))

    def test_install_timeout(self):
        def runner(cmd, **kwargs):
            if cmd[:2] == ["uv", "sync"]:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
            return FakeProc(0, "")

        out = execute_tests_node(
            {
                "execute_tests": True,
                "execute_install": True,
                "repo": "x/y",
                "number": 10,
                "pr_head_sha": "sha",
                "execute_install_timeout_s": 1,
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [SANITIZER, TEST_SAN],
                    "source_files": [SANITIZER],
                },
                "validated_findings": [{"file": SANITIZER, "related_tests": [TEST_SAN]}],
            },
            runner=runner,
            checkout=lambda repo_dir, sha, dest_path, runner=None: self._checkout_uv(dest_path),
            which=_which_map(uv="uv", pytest="pytest"),
        )
        self.assertEqual(out["execution_report"]["skip_reason"], "install_timeout")
        self.assertTrue(out["execution_report"]["skipped"])

    def test_dotdot_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir()
            (root / "tests" / "test_ok.py").write_text("x", encoding="utf-8")
            self.assertIsNone(jail_relpath(root, "../secret.py"))

    def test_manifest_poetry_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "poetry.lock").write_text("p", encoding="utf-8")
            kind, skip = detect_python_manifest(root, which=lambda n: None)
            self.assertEqual(kind, "poetry")
            self.assertEqual(skip, "unsupported_installer=poetry")


if __name__ == "__main__":
    unittest.main(verbosity=2)
