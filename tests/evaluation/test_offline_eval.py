"""run_eval --offline must be green with no GitHub/Ollama/network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.evaluation.run_eval import main


class TestOfflineEval(unittest.TestCase):
    def test_offline_exit_zero(self):
        rc = main(["--offline"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
