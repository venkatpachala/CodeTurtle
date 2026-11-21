"""Compare Python syntax trees across revisions without importing source code."""
from __future__ import annotations

import ast
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.input.snapshot import GitSnapshotProvider, InputError, ReviewSnapshot, SourceNotFound


class SymbolChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    symbol: str
    kind: Literal["function", "async_function", "class", "module"]
    status: Literal["added", "removed", "modified"]
    base_line: int | None = None
    head_line: int | None = None
    signature_changed: bool = False


class ChangeContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot_id: str
    changes: tuple[SymbolChange, ...] = ()
    source_refs: tuple[str, ...] = ()
    unresolved_context: tuple[str, ...] = ()
    limitations: tuple[str, ...] = (
        "Structural changes guide investigation; they do not prove changed runtime behavior.",
        "Symbol renames appear as removal/addition; dynamic dispatch is not resolved.",
    )


def _symbols(content: bytes | None) -> dict[str, tuple[ast.AST, str, str]]:
    if content is None:
        return {}
    tree = ast.parse(content)
    symbols = {}
    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.parents = []
        def visit_symbol(self, node):
            name = ".".join([*self.parents, node.name])
            if name in symbols:
                raise ValueError("duplicate symbol definitions require separate investigation")
            fingerprint = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
            signature = ast.dump(node.args, include_attributes=False) if hasattr(node, "args") else ""
            symbols[name] = (node, fingerprint, signature)
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()
        visit_FunctionDef = visit_symbol
        visit_AsyncFunctionDef = visit_symbol
        visit_ClassDef = visit_symbol
    Visitor().visit(tree)
    statements = [node for node in tree.body if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    if statements:
        module = ast.Module(body=statements, type_ignores=[])
        module.lineno = statements[0].lineno
        symbols["<module>"] = (module, hashlib.sha256(ast.dump(module, include_attributes=False).encode()).hexdigest(), "")
    return symbols


def compare_python(path: str, before: bytes | None, after: bytes | None) -> tuple[SymbolChange, ...]:
    old, new = _symbols(before), _symbols(after)
    changes = []
    for name in sorted(old.keys() | new.keys()):
        left, right = old.get(name), new.get(name)
        if left and right and left[1] == right[1]:
            continue
        node = right[0] if right else left[0]
        kind = "module" if isinstance(node, ast.Module) else "class" if isinstance(node, ast.ClassDef) else "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
        changes.append(SymbolChange(
            path=path, symbol=name, kind=kind,
            status="added" if left is None else "removed" if right is None else "modified",
            base_line=left[0].lineno if left else None, head_line=right[0].lineno if right else None,
            signature_changed=bool(left and right and left[2] != right[2]),
        ))
    return tuple(changes)


def build_change_context(provider: GitSnapshotProvider, snapshot: ReviewSnapshot,
                         paths: list[str], *, max_files: int = 50, max_symbols: int = 100) -> ChangeContext:
    changes, refs, missing = [], [], []
    eligible = sorted({path for path in paths if path.endswith(".py")})
    if len(eligible) > max_files:
        missing.append(f"Python file budget: {len(eligible) - max_files} files omitted")
    for path in eligible[:max_files]:
        sources = []
        try:
            for side in ("base", "head"):
                try:
                    source = provider.read(snapshot, path, side)
                    sources.append(source.content)
                    refs.append(f"{side}:{path}@{source.content_sha256}")
                except SourceNotFound:
                    sources.append(None)
            delta = compare_python(path, *sources)
            remaining = max_symbols - len(changes)
            changes.extend(delta[:remaining])
            if len(delta) > remaining:
                missing.append(f"Symbol budget omitted changes in {path}")
        except (InputError, SyntaxError, ValueError, RecursionError) as exc:
            missing.append(f"{path}: {type(exc).__name__}; structural comparison unavailable")
    return ChangeContext(snapshot_id=snapshot.id, changes=tuple(changes),
                         source_refs=tuple(refs), unresolved_context=tuple(missing))
