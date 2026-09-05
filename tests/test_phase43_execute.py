"""Phase 4.3 — optional pytest execution. Subprocess is mocked."""

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
    collect_test_paths,
    execute_tests_node,
    execution_skip_reason,
    jail_relpath,
    parse_pytest_output,
    resolve_pytest_bin,
)
from core.verification.policy import (
    reattach_stamps,
    recommendation_from_verification,
)

SANITIZER = "api/sql_utils/sql_sanitizer.py"
TEST_SAN = "tests/test_sql_sanitizer.py"
LOCK = "package-lock.json"


class FakeProc:
    def __init__(self, code=0, stdout="12 passed\n", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


class TestSkipGates(unittest.TestCase):
    def test_flag_off_no_subprocess(self):
        calls = []

        def runner(*a, **k):
            calls.append(a)
            raise AssertionError("subprocess must not run")

        with patch("core.verification.execute.settings") as s:
            s.execute_tests = False
            s.execute_timeout_s = 120
            s.execute_max_files = 8
            with patch.dict("os.environ", {"CODETURTLE_EXECUTE_TESTS": ""}, clear=False):
                out = execute_tests_node(
                    {
                        "execute_tests": False,
                        "pr_facts": {"classification": "source", "files_changed": [SANITIZER]},
                        "files_changed": [SANITIZER],
                        "validated_findings": [],
                    },
                    runner=runner,
                )
        self.assertEqual(out["execution_report"]["skip_reason"], "disabled")
        self.assertTrue(out["execution_report"]["skipped"])
        self.assertEqual(calls, [])

    def test_lockfile_only_no_subprocess(self):
        calls = []

        def runner(*a, **k):
            calls.append(a)
            raise AssertionError("no subprocess on lockfile PR")

        out = execute_tests_node(
            {
                "execute_tests": True,
                "pr_facts": {
                    "classification": "lockfile-only",
                    "files_changed": [LOCK],
                    "source_files": [],
                },
                "files_changed": [LOCK],
                "validated_findings": [
                    {"file": LOCK, "related_tests": [], "verification_status": "supported"}
                ],
            },
            runner=runner,
        )
        self.assertEqual(out["execution_report"]["skip_reason"], "lockfile-only")
        self.assertEqual(calls, [])

    def test_skip_reason_helper(self):
        self.assertEqual(execution_skip_reason({"execute_tests": False}), "disabled")
        self.assertEqual(
            execution_skip_reason(
                {
                    "execute_tests": True,
                    "pr_facts": {"classification": "lockfile-only", "files_changed": [LOCK]},
                }
            ),
            "lockfile-only",
        )


class TestPathJail(unittest.TestCase):
    def test_rejects_dotdot_and_absolute(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir()
            (root / "tests" / "test_ok.py").write_text("x", encoding="utf-8")
            self.assertIsNone(jail_relpath(root, "../secret.py"))
            self.assertIsNone(jail_relpath(root, "..\\secret.py"))
            self.assertIsNone(jail_relpath(root, "/etc/passwd"))
            self.assertIsNone(jail_relpath(root, "C:\\Windows\\x.py"))
            self.assertEqual(jail_relpath(root, "tests/test_ok.py"), "tests/test_ok.py")
            self.assertIsNone(jail_relpath(root, "tests/missing.py"))


class TestCollectAndParse(unittest.TestCase):
    def test_collect_related_first(self):
        findings = [
            {"file": SANITIZER, "related_tests": [TEST_SAN]},
        ]
        paths = collect_test_paths(
            findings,
            [SANITIZER, TEST_SAN, "tests/test_other.py"],
            max_files=8,
        )
        self.assertEqual(paths[0], TEST_SAN)
        self.assertIn("tests/test_other.py", paths)

    def test_parse_pytest(self):
        p = parse_pytest_output("12 passed\n", 0)
        self.assertEqual(p["passed"], 12)
        p = parse_pytest_output("FAILED tests/test_x.py::test_a\n1 failed, 2 passed\n", 1)
        self.assertEqual(p["failed"], 1)
        self.assertEqual(p["passed"], 2)
        self.assertTrue(p["failed_names"])


class TestExecuteHappyAndFail(unittest.TestCase):
    def _checkout(self, dest: Path):
        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            (dest_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            tests = dest_path / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_sql_sanitizer.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            return True, ""

        return fake_checkout

    def test_fake_pytest_pass_status_unchanged(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(list(cmd))
            return FakeProc(0, "12 passed\n")

        findings = [
            {
                "id": "a",
                "file": SANITIZER,
                "related_tests": [TEST_SAN],
                "verification_status": "supported",
                "severity": "concern",
                "title": "quoter",
            }
        ]
        state = {
            "execute_tests": True,
            "repo": "FalkorDB/QueryWeaver",
            "number": 538,
            "pr_head_sha": "abc123",
            "pr_facts": {
                "classification": "source",
                "files_changed": [SANITIZER, TEST_SAN],
                "source_files": [SANITIZER],
            },
            "files_changed": [SANITIZER, TEST_SAN],
            "validated_findings": findings,
            "findings": findings,
        }
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "wt"
            # Do not pick up repos/<clone>/.venv from a live checkout on this machine.
            missing_clone = Path(td) / "no-clone"
            with patch(
                "core.verification.execute.resolve_repo_dir",
                return_value=missing_clone,
            ):
                out = execute_tests_node(
                    state,
                    runner=runner,
                    checkout=self._checkout(dest),
                    which=lambda n: "pytest",
                )
        self.assertFalse(out["execution_report"]["skipped"])
        self.assertEqual(out["execution_report"]["exit_code"], 0)
        self.assertEqual(out["validated_findings"][0]["verification_status"], "supported")
        self.assertTrue(out["validated_findings"][0]["tests_run"])
        self.assertTrue(out["validated_findings"][0]["tests_passed"])
        pytest_cmds = [
            c for c in calls if any("pytest" in str(x) for x in c)
        ]
        self.assertTrue(pytest_cmds)
        self.assertIn(TEST_SAN, pytest_cmds[0] or pytest_cmds[-1])

    def test_fake_pytest_fail_policy_request_changes(self):
        def runner(cmd, **kwargs):
            return FakeProc(1, "FAILED tests/test_sql_sanitizer.py::test_x\n1 failed\n")

        findings = [
            {
                "file": SANITIZER,
                "related_tests": [TEST_SAN],
                "verification_status": "uncertain",
                "severity": "nit",
                "title": "add tests",
            }
        ]
        state = {
            "execute_tests": True,
            "repo": "FalkorDB/QueryWeaver",
            "number": 538,
            "pr_head_sha": "abc",
            "pr_facts": {
                "classification": "source",
                "files_changed": [SANITIZER, TEST_SAN],
                "source_files": [SANITIZER],
            },
            "validated_findings": findings,
        }
        out = execute_tests_node(
            state,
            runner=runner,
            checkout=self._checkout(Path("x")),
            which=lambda n: "pytest",
        )
        self.assertFalse(out["execution_report"]["skipped"])
        self.assertEqual(out["validated_findings"][0]["tests_passed"], False)
        rec = recommendation_from_verification(
            out["validated_findings"], classification="source", risk="low"
        )
        self.assertEqual(rec, "REQUEST_CHANGES")

    def test_no_runner(self):
        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            return True, ""

        out = execute_tests_node(
            {
                "execute_tests": True,
                "repo": "x/y",
                "number": 1,
                "pr_head_sha": "sha",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [SANITIZER, TEST_SAN],
                    "source_files": [SANITIZER],
                },
                "validated_findings": [
                    {"file": SANITIZER, "related_tests": [TEST_SAN]}
                ],
            },
            runner=lambda *a, **k: FakeProc(0, ""),
            checkout=fake_checkout,
            which=lambda n: None,
        )
        self.assertEqual(out["execution_report"]["skip_reason"], "no_runner")

    def test_timeout_fail_closed(self):
        def runner(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

        out = execute_tests_node(
            {
                "execute_tests": True,
                "repo": "x/y",
                "number": 1,
                "pr_head_sha": "sha",
                "execute_timeout_s": 1,
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [SANITIZER, TEST_SAN],
                    "source_files": [SANITIZER],
                },
                "validated_findings": [
                    {"file": SANITIZER, "related_tests": [TEST_SAN]}
                ],
            },
            runner=runner,
            checkout=self._checkout(Path("x")),
            which=lambda n: "pytest",
        )
        self.assertTrue(out["execution_report"]["skipped"])
        self.assertEqual(out["execution_report"]["skip_reason"], "timeout")

    def test_dotdot_not_passed_to_pytest(self):
        captured = []

        def runner(cmd, **kwargs):
            captured.append(list(cmd))
            return FakeProc(0, "1 passed\n")

        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            (dest_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            (dest_path / "tests").mkdir(exist_ok=True)
            (dest_path / "tests" / "test_sql_sanitizer.py").write_text("x", encoding="utf-8")
            return True, ""

        execute_tests_node(
            {
                "execute_tests": True,
                "repo": "x/y",
                "number": 1,
                "pr_head_sha": "sha",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [SANITIZER, "../evil.py", TEST_SAN],
                    "source_files": [SANITIZER],
                },
                "validated_findings": [
                    {"file": SANITIZER, "related_tests": ["../evil.py", TEST_SAN]}
                ],
            },
            runner=runner,
            checkout=fake_checkout,
            which=lambda n: "pytest",
        )
        pytest_cmds = [c for c in captured if c and str(c[0]).endswith("pytest") or (c and c[0] == "pytest")]
        self.assertTrue(pytest_cmds)
        flat = " ".join(pytest_cmds[-1])
        self.assertNotIn("..", flat)
        self.assertIn("tests/test_sql_sanitizer.py", flat)

    def test_prefers_worktree_venv_pytest(self):
        captured = []

        def runner(cmd, **kwargs):
            captured.append(list(cmd))
            return FakeProc(0, "1 passed\n")

        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            (dest_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            tests = dest_path / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_sql_sanitizer.py").write_text("x", encoding="utf-8")
            scripts = dest_path / ".venv" / "Scripts"
            scripts.mkdir(parents=True, exist_ok=True)
            (scripts / "pytest.exe").write_text("", encoding="utf-8")
            (dest_path / ".venv" / "bin").mkdir(exist_ok=True)
            (dest_path / ".venv" / "bin" / "pytest").write_text("", encoding="utf-8")
            return True, ""

        execute_tests_node(
            {
                "execute_tests": True,
                "repo": "x/y",
                "number": 2,
                "pr_head_sha": "sha",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [SANITIZER, TEST_SAN],
                    "source_files": [SANITIZER],
                },
                "validated_findings": [
                    {"file": SANITIZER, "related_tests": [TEST_SAN]}
                ],
            },
            runner=runner,
            checkout=fake_checkout,
            which=lambda n: "global-pytest",
        )
        pytest_cmds = [c for c in captured if c and "pytest" in str(c[0]).lower()]
        self.assertTrue(pytest_cmds)
        self.assertIn(".venv", pytest_cmds[0][0].replace("\\", "/"))
        self.assertNotEqual(pytest_cmds[0][0], "global-pytest")

    def test_resolve_pytest_bin_order(self):
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td) / "wt"
            clone = Path(td) / "clone"
            wt.mkdir()
            clone.mkdir()
            self.assertIsNone(resolve_pytest_bin(wt, clone, which=lambda n: None))
            self.assertEqual(
                resolve_pytest_bin(wt, clone, which=lambda n: "/usr/bin/pytest"),
                "/usr/bin/pytest",
            )


class TestGraphAndPolicy(unittest.TestCase):
    def test_graph_has_execute_after_verify(self):
        from core.graph import build_review_graph

        nodes = set(build_review_graph().get_graph().nodes)
        self.assertIn("execute_tests", nodes)
        self.assertIn("verify_findings", nodes)

    def test_lockfile_comment_unchanged_when_execute_skipped(self):
        rec = recommendation_from_verification(
            [
                {
                    "verification_status": "supported",
                    "severity": "concern",
                    "file": LOCK,
                    "tests_run": False,
                }
            ],
            classification="lockfile-only",
            risk="low",
            execution={"skipped": True, "skip_reason": "lockfile-only"},
        )
        self.assertEqual(rec, "COMMENT")

    def test_execution_report_failed_requests_changes(self):
        rec = recommendation_from_verification(
            [{"verification_status": "uncertain", "severity": "nit", "file": SANITIZER}],
            classification="source",
            risk="low",
            execution={"skipped": False, "exit_code": 1, "failed": 1, "passed": 0},
        )
        self.assertEqual(rec, "REQUEST_CHANGES")

    def test_reattach_stamps_survives_critic_schema(self):
        original = [
            {
                "title": "quoter",
                "file": SANITIZER,
                "verification_status": "supported",
                "tests_run": True,
                "tests_passed": False,
            }
        ]
        llm_out = [{"title": "quoter", "file": SANITIZER, "severity": "concern"}]
        merged = reattach_stamps(llm_out, original)
        self.assertEqual(merged[0]["verification_status"], "supported")
        self.assertEqual(merged[0]["tests_passed"], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
