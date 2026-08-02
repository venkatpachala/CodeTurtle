from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CallSite:
    caller_name: str
    caller_line: int
    callee_name: str
    call_line: int
    is_attribute: bool = False


@dataclass
class FileCalls:
    path: str
    calls: List[CallSite] = field(default_factory=list)


class CallExtractor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.calls: List[CallSite] = []
        self._stack: List[tuple[str, int]] = []

    def extract(self, tree: ast.AST) -> FileCalls:
        self.visit(tree)
        return FileCalls(path=self.path, calls=self.calls)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._stack.append((node.name, node.lineno))
        self.generic_visit(node)
        self._stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._stack.append((node.name, node.lineno))
        self.generic_visit(node)
        self._stack.pop()

    def visit_Call(self, node: ast.Call):
        if self._stack:
            caller_name, caller_line = self._stack[-1]
            callee, is_attr = self._callee_name(node.func)
            if callee:
                self.calls.append(
                    CallSite(
                        caller_name=caller_name,
                        caller_line=caller_line,
                        callee_name=callee,
                        call_line=getattr(node, "lineno", 0),
                        is_attribute=is_attr,
                    )
                )
        self.generic_visit(node)

    def _callee_name(self, func: ast.AST) -> tuple[Optional[str], bool]:
        if isinstance(func, ast.Name):
            return func.id, False
        if isinstance(func, ast.Attribute):
            return func.attr, True
        return None, False