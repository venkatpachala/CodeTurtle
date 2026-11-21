"""Narrow symbolic checks for direct Python None triggers; never execute source.

Unsupported control flow returns unknown. This is not a general program analyzer.
"""
from __future__ import annotations

import ast
import re

_FALLTHROUGH = object()


def function_at(source: str, symbol: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    short = symbol.rsplit(".", 1)[-1]
    matches = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == short]
    return matches[0] if len(matches) == 1 else None


def _condition(node: ast.AST, names: set[str]) -> bool | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _condition(node.operand, names)
        return not value if value is not None else None
    if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
        left, right = node.left, node.comparators[0]
        known = ((isinstance(left, ast.Name) and left.id in names and isinstance(right, ast.Constant) and right.value is None)
                 or (isinstance(right, ast.Name) and right.id in names and isinstance(left, ast.Constant) and left.value is None))
        if known and isinstance(node.ops[0], (ast.Is, ast.IsNot)):
            return isinstance(node.ops[0], ast.Is)
    return None


def _walk(statements: list[ast.stmt], names: set[str], anchor: int) -> bool | None | object:
    for statement in statements:
        if isinstance(statement, ast.If):
            condition = _condition(statement.test, names)
            if condition is None:
                return None
            result = _walk(statement.body if condition else statement.orelse, names, anchor)
            if result is not _FALLTHROUGH:
                return result
        elif isinstance(statement, (ast.Return, ast.Raise)):
            # True means the claimed operation is reached; False means earlier termination.
            return bool(statement.lineno <= anchor <= statement.end_lineno)
        elif isinstance(statement, ast.Pass) or (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)):
            continue
        else:
            return None
    return _FALLTHROUGH


def none_trigger_reaches_anchor(source: str, symbol: str, trigger: str, snippet: str) -> tuple[bool, bool | None]:
    """Return (applicable, reachable) for a tightly bounded direct None invocation."""
    if not re.search(r"\bNone\b", trigger):
        return False, None
    function = function_at(source, symbol)
    if function is None or function.decorator_list:
        return True, None
    arguments = {argument.arg for argument in function.args.args}
    names = {name for name in re.findall(r"\b([A-Za-z_]\w*)\s+is\s+None\b", trigger) if name in arguments}
    if not names and len(function.args.args) == 1 and re.search(rf"\b{re.escape(function.name)}\(\s*None\s*\)", trigger):
        names = {function.args.args[0].arg}
    if not names:
        return True, None
    lines = source.splitlines()
    anchors = [number for number, line in enumerate(lines, 1) if line.strip() == snippet.strip()
               and function.lineno < number <= function.end_lineno]
    if len(anchors) != 1:
        return True, None
    result = _walk(function.body, names, anchors[0])
    return True, False if result is _FALLTHROUGH else result
