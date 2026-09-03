"""Phase 4.3c — path-limited JS tests. Subprocess is mocked."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.verification.execute import execute_tests_node

MODAL = "app/src/components/modals/DatabaseModal.tsx"
MODAL_TEST = "app/src/components/modals/DatabaseModal.test.tsx"
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


def _write_pkg(dest: Path, *, vitest: bool = True, test_script: str | None = "vitest"):
    app = dest / "app"
    app.mkdir(parents=True, exist_ok=True)
    pkg: dict = {
        "name": "queryweaver-app",
        "scripts": {},
        "devDependencies": {},
    }
    if test_script is not None:
        pkg["scripts"]["test"] = test_script
    if vitest:
        pkg["devDependencies"]["vitest"] = "^2.0.0"
    (app / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (app / "package-lock.json").write_text("{}", encoding="utf-8")
    modal_dir = app / "src" / "components" / "modals"
    modal_dir.mkdir(parents=True, exist_ok=True)
    (modal_dir / "DatabaseModal.tsx").write_text("export const X=1\n", encoding="utf-8")
    (modal_dir / "DatabaseModal.test.tsx").write_text("test('x', () => {})\n", encoding="utf-8")
    return app


class TestJsSkip(unittest.TestCase):
    def test_python_only_no_js_targets(self):
        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            (dest_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            tests = dest_path / "tests"
            tests.mkdir(exist_ok=True)
            (tests / "test_sql_sanitizer.py").write_text("x", encoding="utf-8")
            return True, ""

        calls = []

        def runner(cmd, **kwargs):
            calls.append(list(cmd))
            self.assertTrue(kwargs.get("shell") in (None, False))
            return FakeProc(0, "1 passed\n")

        out = execute_tests_node(
            {
                "execute_tests": True,
                "repo": "x/y",
                "number": 20,
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
            which=_which_map(pytest="pytest", npm="npm", npx="npx"),
        )
        self.assertEqual(out["execution_report"]["js"]["skip_reason"], "no_js_targets")
        npm = [c for c in calls if c and str(c[0]) in ("npm", "npx")]
        self.assertEqual(npm, [])

    def test_no_package_json(self):
        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            p = dest_path / "src"
            p.mkdir(exist_ok=True)
            (p / "Modal.test.tsx").write_text("x", encoding="utf-8")
            return True, ""

        out = execute_tests_node(
            {
                "execute_tests": True,
                "repo": "x/y",
                "number": 21,
                "pr_head_sha": "sha",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": ["src/Modal.tsx", "src/Modal.test.tsx"],
                    "source_files": ["src/Modal.tsx"],
                },
                "validated_findings": [
                    {"file": "src/Modal.tsx", "related_tests": ["src/Modal.test.tsx"]}
                ],
            },
            runner=lambda *a, **k: FakeProc(0, ""),
            checkout=fake_checkout,
            which=_which_map(npx="npx", npm="npm"),
        )
        self.assertEqual(out["execution_report"]["js"]["skip_reason"], "no_js_runner")

    def test_lockfile_only_no_npm(self):
        calls = []

        def runner(*a, **k):
            calls.append(a)
            raise AssertionError("no npm on lockfile PR")

        out = execute_tests_node(
            {
                "execute_tests": True,
                "execute_install": True,
                "pr_facts": {
                    "classification": "lockfile-only",
                    "files_changed": [LOCK],
                },
                "validated_findings": [{"file": LOCK}],
            },
            runner=runner,
        )
        self.assertEqual(out["execution_report"]["skip_reason"], "lockfile-only")
        self.assertEqual(calls, [])


class TestJsRun(unittest.TestCase):
    def test_modal_vitest_jailed(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(list(cmd))
            self.assertTrue(kwargs.get("shell") in (None, False))
            joined = " ".join(str(c) for c in cmd)
            if "vitest" in joined:
                return FakeProc(0, "1 passed\n")
            return FakeProc(0, "1 passed\n")

        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            app = _write_pkg(dest_path)
            (app / "node_modules").mkdir()
            return True, ""

        out = execute_tests_node(
            {
                "execute_tests": True,
                "repo": "x/y",
                "number": 22,
                "pr_head_sha": "sha",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [MODAL, MODAL_TEST],
                    "source_files": [MODAL],
                },
                "validated_findings": [
                    {
                        "file": MODAL,
                        "related_tests": [MODAL_TEST],
                        "verification_status": "supported",
                    }
                ],
            },
            runner=runner,
            checkout=fake_checkout,
            which=_which_map(npx="npx", npm="npm"),
        )
        self.assertFalse(out["execution_report"]["js"]["skipped"])
        vitest = [c for c in calls if c and "vitest" in c]
        self.assertTrue(vitest)
        flat = " ".join(vitest[-1])
        self.assertIn("DatabaseModal.test.tsx", flat)
        self.assertNotIn("..", flat)
        self.assertTrue(out["validated_findings"][0]["tests_run"])
        self.assertTrue(out["validated_findings"][0]["tests_passed"])
        self.assertEqual(out["validated_findings"][0]["verification_status"], "supported")

    def test_execute_install_npm_ci_ignore_scripts(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(list(cmd))
            self.assertTrue(kwargs.get("shell") in (None, False))
            if cmd[:2] == ["npm", "ci"]:
                return FakeProc(0, "ok")
            if "vitest" in cmd:
                return FakeProc(0, "1 passed\n")
            return FakeProc(0, "")

        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            _write_pkg(dest_path)
            return True, ""

        execute_tests_node(
            {
                "execute_tests": True,
                "execute_install": True,
                "repo": "x/y",
                "number": 23,
                "pr_head_sha": "sha",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [MODAL, MODAL_TEST],
                    "source_files": [MODAL],
                },
                "validated_findings": [
                    {"file": MODAL, "related_tests": [MODAL_TEST]}
                ],
            },
            runner=runner,
            checkout=fake_checkout,
            which=_which_map(npx="npx", npm="npm"),
        )
        ci = [c for c in calls if c[:2] == ["npm", "ci"]]
        self.assertTrue(ci)
        self.assertIn("--ignore-scripts", ci[0])

    def test_npm_ci_fail(self):
        def runner(cmd, **kwargs):
            if cmd[:2] == ["npm", "ci"]:
                return FakeProc(1, "", "boom")
            if "vitest" in cmd:
                raise AssertionError("vitest must not run after js_install_failed")
            return FakeProc(0, "")

        def fake_checkout(repo_dir, sha, dest_path, runner=None):
            dest_path.mkdir(parents=True, exist_ok=True)
            _write_pkg(dest_path)
            return True, ""

        out = execute_tests_node(
            {
                "execute_tests": True,
                "execute_install": True,
                "repo": "x/y",
                "number": 24,
                "pr_head_sha": "sha",
                "pr_facts": {
                    "classification": "source",
                    "files_changed": [MODAL, MODAL_TEST],
                    "source_files": [MODAL],
                },
                "validated_findings": [
                    {"file": MODAL, "related_tests": [MODAL_TEST]}
                ],
            },
            runner=runner,
            checkout=fake_checkout,
            which=_which_map(npx="npx", npm="npm"),
        )
        self.assertEqual(out["execution_report"]["js"]["skip_reason"], "js_install_failed")
        self.assertTrue(out["execution_report"]["js"]["skipped"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
