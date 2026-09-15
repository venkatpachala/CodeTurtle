"""V4.1 — BundleBuilder. Synthetic paths only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bundling.builder import BundleBuilder
from core.change_units import build_change_units, format_units
from core.pr_facts import build_pr_facts, source_first_paths

LOADER = "pkg/api/loader.py"
PIPELINE = "pkg/api/pipeline.py"
MAIN = "pkg/cli/main.py"
TEST_LOADER = "tests/test_loader.py"
TEST_OTHER = "tests/test_other.py"
README = "README.md"
LOCK = "package-lock.json"

FILES = [LOADER, PIPELINE, MAIN, TEST_LOADER, README, LOCK]


def _hunk(path: str, added: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,1 +1,4 @@\n"
        f" context\n"
        f"{added}"
    )


DIFF = "".join(
    [
        _hunk(LOADER, "+def load():\n+    return 1\n"),
        _hunk(PIPELINE, "+def run():\n+    return load()\n"),
        _hunk(MAIN, "+def main():\n+    pass\n"),
        _hunk(TEST_LOADER, "+def test_load():\n+    assert load() == 1\n"),
        _hunk(README, "+# docs\n"),
        _hunk(LOCK, '+  "lockfileVersion": 3\n'),
    ]
)


class TestSourceFirstPacking(unittest.TestCase):
    def test_md_and_lock_not_first_when_source_present(self):
        ordered = source_first_paths([README, LOCK, LOADER])
        self.assertEqual(ordered[0], LOADER)
        self.assertIn(README, ordered)
        self.assertIn(LOCK, ordered)

    def test_format_units_does_not_lead_with_docs(self):
        units = build_change_units(DIFF, [README, LOADER, LOCK])
        packed, _cov = format_units(units, lockfile_only=False)
        first = packed.find("### CU-")
        self.assertGreaterEqual(first, 0)
        window = packed[first : first + 80]
        self.assertIn("loader.py", window)
        self.assertNotIn("README.md:", window)


class TestBundleBuilder(unittest.TestCase):
    def test_loader_grouped_with_its_test_docs_dropped(self):
        facts = build_pr_facts(title="api", files_changed=FILES, full_diff=DIFF)
        units = build_change_units(DIFF, FILES)
        bundles = BundleBuilder().build(
            files_changed=FILES,
            units=units,
            classification=str(facts.get("classification") or "mixed"),
        )
        self.assertTrue(bundles)
        self.assertLessEqual(len(bundles), 4)
        all_paths = [p for b in bundles for p in b.paths]
        self.assertNotIn(TEST_OTHER, all_paths)
        self.assertNotIn(README, all_paths)
        self.assertNotIn(LOCK, all_paths)
        matched = [
            b
            for b in bundles
            if LOADER in b.paths and TEST_LOADER in b.paths
        ]
        self.assertTrue(matched, f"expected loader+test_loader together, got {all_paths}")
        for b in matched:
            self.assertEqual(b.kind, "source")
            self.assertNotIn(README, b.paths)
        for b in bundles:
            self.assertLessEqual(len(b.paths), 6)

    def test_unlisted_test_not_invented(self):
        units = build_change_units(DIFF, FILES)
        bundles = BundleBuilder().build(
            files_changed=FILES,
            units=units,
            classification="mixed",
        )
        all_paths = [p for b in bundles for p in b.paths]
        self.assertNotIn(TEST_OTHER, all_paths)


class TestFeatureStemJoin(unittest.TestCase):
    def test_hosted_jobs_joins_matching_test_not_jobs_py(self):
        hosted_jobs = "pkg/cli/hosted_jobs.py"
        jobs = "pkg/cli/jobs.py"
        hosted_cfg = "pkg/hosted/config.py"
        test_regrade = "tests/test_hosted_regrade.py"
        files = [hosted_jobs, jobs, hosted_cfg, test_regrade]
        diff = "".join(
            [
                _hunk(hosted_jobs, "+def run_hosted_regrade():\n+    return 1\n"),
                _hunk(jobs, "+def regrade():\n+    pass\n"),
                _hunk(hosted_cfg, "+class HostedRegradeSource:\n+    pass\n"),
                _hunk(test_regrade, "+def test_hosted_regrade():\n+    assert True\n"),
            ]
        )
        units = build_change_units(diff, files)
        bundles = BundleBuilder().build(
            files_changed=files,
            units=units,
            classification="source",
        )
        self.assertTrue(bundles)
        self.assertLessEqual(len(bundles), 4)
        matched = [
            b
            for b in bundles
            if hosted_jobs in b.paths and test_regrade in b.paths
        ]
        self.assertTrue(
            matched,
            f"expected hosted_jobs+test together, got {[b.paths for b in bundles]}",
        )
        for b in bundles:
            if b.paths == [test_regrade] or (
                all(p.endswith(".py") and "test_" in p.split("/")[-1] for p in b.paths)
                and not any("hosted_jobs" in p or "/hosted/" in p for p in b.paths)
            ):
                self.fail(f"test-only bundle: {b.paths}")
            self.assertNotEqual(b.paths, [test_regrade])
        hosted_bundle = matched[0]
        self.assertNotIn(jobs, hosted_bundle.paths)
        self.assertIn(hosted_cfg, hosted_bundle.paths)

    def test_harbor_shaped_paths_split_jobs_and_trials(self):
        hosted_jobs = "src/harbor/cli/hosted_jobs.py"
        jobs = "src/harbor/cli/jobs.py"
        trials = "src/harbor/cli/trials.py"
        hosted_cfg = "src/harbor/hosted/config.py"
        hosted_submit = "src/harbor/hosted/submit.py"
        job = "src/harbor/job.py"
        test_regrade = "tests/unit/test_hosted_regrade.py"
        files = [
            hosted_jobs,
            jobs,
            trials,
            hosted_cfg,
            hosted_submit,
            job,
            test_regrade,
        ]
        diff = "".join(
            [
                _hunk(hosted_jobs, "+def run_hosted_regrade():\n+    return 1\n"),
                _hunk(jobs, "+def regrade():\n+    pass\n"),
                _hunk(trials, "+def list_trials():\n+    pass\n"),
                _hunk(hosted_cfg, "+class HostedRegradeSource:\n+    pass\n"),
                _hunk(hosted_submit, "+def submit():\n+    pass\n"),
                _hunk(job, "+class Job:\n+    pass\n"),
                _hunk(test_regrade, "+def test_hosted_regrade():\n+    assert True\n"),
            ]
        )
        units = build_change_units(diff, files)
        bundles = BundleBuilder().build(
            files_changed=files,
            units=units,
            classification="source",
        )
        self.assertTrue(bundles)
        self.assertLessEqual(len(bundles), 4)
        hosted = [
            b
            for b in bundles
            if hosted_jobs in b.paths and test_regrade in b.paths
        ]
        self.assertTrue(
            hosted,
            f"expected hosted_jobs+test together, got {[b.paths for b in bundles]}",
        )
        hb = hosted[0]
        self.assertIn(hosted_cfg, hb.paths)
        self.assertIn(hosted_submit, hb.paths)
        self.assertNotIn(jobs, hb.paths)
        self.assertNotIn(trials, hb.paths)
        self.assertNotIn(job, hb.paths)
        jobs_bundle = next((b for b in bundles if jobs in b.paths), None)
        trials_bundle = next((b for b in bundles if trials in b.paths), None)
        if jobs_bundle is not None and trials_bundle is not None:
            if jobs_bundle is trials_bundle:
                self.fail(f"jobs.py and trials.py shared a bundle: {jobs_bundle.paths}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
