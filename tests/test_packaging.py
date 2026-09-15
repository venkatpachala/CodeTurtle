"""Packaging contract for the installable `codeturtle` console script. No mocks."""

from __future__ import annotations

import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestPyproject(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_project_name_and_version(self):
        project = self.data["project"]
        self.assertEqual(project["name"], "codeturtle-review")
        self.assertEqual(project["version"], "0.2.0")
        self.assertGreaterEqual(project["requires-python"], ">=3.11")

    def test_console_script(self):
        scripts = self.data["project"]["scripts"]
        self.assertEqual(scripts["codeturtle"], "cli.main:app")

    def test_build_system(self):
        build = self.data["build-system"]
        self.assertIn("hatchling", " ".join(build["requires"]))
        self.assertEqual(build["build-backend"], "hatchling.build")

    def test_required_deps_do_not_force_optional_backends(self):
        deps = " ".join(self.data["project"]["dependencies"]).lower()
        for needle in ("qdrant", "neo4j", "langfuse", "graphifyy", "langchain-ollama"):
            self.assertNotIn(needle, deps)

    def test_optional_extras_declared(self):
        extras = self.data["project"]["optional-dependencies"]
        for name in ("ollama", "openai", "langfuse", "graphify", "qdrant", "neo4j"):
            self.assertIn(name, extras)
            self.assertTrue(extras[name])

    def test_wheel_packages_exclude_tests_and_evals(self):
        wheel = self.data["tool"]["hatch"]["build"]["targets"]["wheel"]
        packages = wheel["packages"]
        self.assertIn("cli", packages)
        self.assertIn("core", packages)
        self.assertNotIn("tests", packages)
        self.assertNotIn("evals", packages)

    def test_license_and_env_example_exist(self):
        self.assertTrue((ROOT / "LICENSE").is_file())
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("GITHUB_TOKEN=", example)
        self.assertIn("OLLAMA_MODEL=", example)
        self.assertIn("LLM_BACKEND=ollama", example)


class TestTyperAppSymbol(unittest.TestCase):
    def test_cli_main_app_is_callable(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from cli.main import app

        self.assertTrue(callable(app))
        self.assertEqual(getattr(app, "info").name, "codeturtle")


if __name__ == "__main__":
    unittest.main(verbosity=2)
