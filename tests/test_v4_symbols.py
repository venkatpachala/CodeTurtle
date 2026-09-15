"""V4.3 — identifier symbols only. No paths, no 'py'."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.graphctx.symbols import extract_identifiers, is_valid_symbol

LOADER = "pkg/api/loader.py"

HUNK = """@@ -10,3 +10,8 @@
 context
+def refresh_schema():
+    return True
+class Loader:
+    pass
"""


class TestValidSymbol(unittest.TestCase):
    def test_accept_identifier(self):
        self.assertTrue(is_valid_symbol("refresh_schema"))
        self.assertTrue(is_valid_symbol("Loader"))
        self.assertTrue(is_valid_symbol("_private"))

    def test_reject_dot_slash_and_py(self):
        self.assertFalse(is_valid_symbol("py"))
        self.assertFalse(is_valid_symbol("PY"))
        self.assertFalse(is_valid_symbol("loader.py"))
        self.assertFalse(is_valid_symbol("*.py"))
        self.assertFalse(is_valid_symbol("pkg/api/loader.py"))
        self.assertFalse(is_valid_symbol("pkg.api.loader"))
        self.assertFalse(is_valid_symbol(""))


class TestExtractIdentifiers(unittest.TestCase):
    def test_ast_and_fallback_from_hunk(self):
        names = extract_identifiers(HUNK, LOADER)
        self.assertIn("refresh_schema", names)
        self.assertIn("Loader", names)
        self.assertNotIn("py", names)
        self.assertFalse(any("." in n or "/" in n for n in names))

    def test_fallback_def_name(self):
        excerpt = "+def load_data(x):\n+    return x\n"
        names = extract_identifiers(excerpt, LOADER)
        self.assertIn("load_data", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
