"""Conservative contradiction checks, never a general semantic verifier.

Only a single directly named Python scalar assignment/keyword is recognized.
Computed values, multiple matches, and other languages deliberately abstain.
"""
from __future__ import annotations

import ast
import textwrap


def contradicts_literal(code: str, property_name: str, claimed: str,
                        path: str, kind: str) -> bool:
    if kind != "literal" or not path.endswith(".py"):
        return False
    name = property_name.rsplit(".", 1)[-1]
    source = textwrap.dedent(code).strip()
    trees = []
    for candidate in (source, "_capture(\n" + source + "\n)"):
        try:
            trees.append(ast.parse(candidate))
            break
        except SyntaxError:
            continue
    if not trees:
        return False
    values = []
    for node in ast.walk(trees[0]):
        value = None
        if isinstance(node, ast.keyword) and node.arg == name:
            value = node.value
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, (str, int, float, bool, type(None))):
            values.append(value.value)
    if len(values) != 1:
        return False
    value = values[0]
    # String casing matters (e.g. GET vs get). Canonical scalar spellings only.
    return str(value) != claimed
