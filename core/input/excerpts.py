"""Bounded, line-preserving Python scopes; no source is imported or executed."""
from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceExcerpt:
    text: str
    start_line: int
    scope: str
    symbol: str
    complete: bool
    unresolved_dependencies: tuple[str, ...] = ()


_BUILTINS = {"len", "isinstance", "issubclass", "abs", "min", "max", "sum", "all", "any",
             "bool", "int", "float", "str", "list", "tuple", "dict", "set", "range", "enumerate",
             "zip", "sorted", "reversed", "round", "ValueError", "TypeError", "RuntimeError"}


def _dependencies(tree: ast.Module, node: ast.FunctionDef | ast.AsyncFunctionDef, qualified: str) -> tuple[str, ...]:
    args = node.args
    parameters = {arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    parameters.update(arg.arg for arg in (args.vararg, args.kwarg) if arg is not None)
    bound = parameters | {item.id for item in ast.walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del))}
    bound.update(item.name for item in ast.walk(node) if isinstance(item, ast.ExceptHandler) and item.name)
    loaded = {item.id for item in ast.walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}
    unresolved = set(loaded - bound - _BUILTINS)
    # Builtins may be shadowed by module definitions/imports/assignments.
    module_bound = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_bound.add(statement.name)
        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
            module_bound.update(alias.asname or alias.name.split(".")[0] for alias in statement.names)
            if any(alias.name == "*" for alias in statement.names):
                unresolved.add("wildcard module import")
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            module_bound.update(item.id for item in ast.walk(statement) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store))
            if statement.value is not None:
                try:
                    ast.literal_eval(statement.value)
                except (ValueError, TypeError, SyntaxError, RecursionError):
                    unresolved.add("dynamic module initialization")
        elif not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)):
            unresolved.add("dynamic module initialization")
        if isinstance(statement, ast.ClassDef):
            unresolved.add("class initialization outside captured scope")
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.decorator_list or any(isinstance(item, ast.Call) for item in ast.walk(statement.args)):
                unresolved.add("dynamic definition initialization")
    unresolved.update(loaded & _BUILTINS & module_bound)
    if "." in qualified:
        unresolved.add("enclosing class or closure")
    if node.decorator_list:
        unresolved.add("function decorators")
    for item in ast.walk(node):
        if isinstance(item, (ast.Global, ast.Nonlocal, ast.Import, ast.ImportFrom)):
            unresolved.add("dynamic or imported function bindings")
        if isinstance(item, ast.Attribute):
            unresolved.add("attribute contract")
        if isinstance(item, ast.Call) and (not isinstance(item.func, ast.Name)
                or item.func.id not in _BUILTINS or item.func.id in bound):
            unresolved.add("external or dynamic call")
        if item is not node and isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            unresolved.add("nested scope")
    return tuple(sorted(unresolved))


def capture_excerpt(content: str, path: str, *, symbol: str = "", anchor: int = 1,
                    max_lines: int = 120, max_chars: int = 5000) -> SourceExcerpt:
    """Success is complete *within the declared scope*, never whole-repo proof.

    A non-file scope is conclusive only when the selected module function has no
    unresolved lexical dependencies under ordinary Python name lookup. Dynamic
    runtime monkey-patching and external caller contracts are outside that scope.
    """
    if min(max_lines, max_chars, anchor) <= 0:
        raise ValueError("excerpt limits and anchor must be positive")
    lines = content.splitlines()
    if len(lines) <= max_lines and len("\n".join(lines)) <= max_chars:
        return SourceExcerpt("\n".join(lines), 1, "file", "", True)
    selected = None
    if path.endswith(".py"):
        try:
            tree = ast.parse(content)
            functions = []
            def visit(body, parents=()):
                for item in body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        name = ".".join((*parents, item.name))
                        if not isinstance(item, ast.ClassDef):
                            functions.append((name, item))
                        visit(item.body, (*parents, item.name))
            visit(tree.body)
            matches = [(name, node) for name, node in functions
                       if name == symbol or (not symbol and node.lineno <= anchor <= node.end_lineno)]
            if len(matches) == 1:
                name, node = matches[0]
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                text = "\n".join(lines[start - 1:node.end_lineno])
                dependencies = _dependencies(tree, node, name)
                if node.end_lineno - start + 1 <= max_lines and len(text) <= max_chars:
                    return SourceExcerpt(text, start, "python_function", name, True, dependencies)
                selected = anchor if start <= anchor <= node.end_lineno else start
        except (SyntaxError, ValueError, RecursionError):
            pass
    start = max(1, (selected or anchor) - 20)
    selected_lines = []
    for line in lines[start - 1:start - 1 + max_lines]:
        if len("\n".join([*selected_lines, line])) > max_chars:
            break
        selected_lines.append(line)
    return SourceExcerpt("\n".join(selected_lines), start, "window", symbol, False,
                         ("complete requested source scope unavailable",))
