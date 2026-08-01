from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional

from core.repository_intelligence.models import (
    ParsedFile,
    Symbol,
    SourceSpan,
    NodeID,
)
from core.repository_intelligence.parsers.base import BaseParser


class PythonParser(BaseParser):
    language = "python"

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".py"

    def parse(self, path: Path, repo_name: str, relative_path: str | None = None) -> ParsedFile:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            content = ""

        # Prefer explicit relative path from compiler
        rel = (relative_path or str(path)).replace("\\", "/")

        symbols: list[Symbol] = []
        imports: list[str] = []

        if content.strip():
            try:
                tree = ast.parse(content)
                symbols, imports = self._extract(tree, rel, repo_name)
            except SyntaxError:
                pass

        return ParsedFile(
            path=rel,
            language=self.language,
            content=content,
            symbols=symbols,
            imports=imports,
            line_count=content.count("\n") + 1 if content else 0,
            size_bytes=len(content.encode("utf-8")),
        )

    def _extract(
        self,
        tree: ast.AST,
        file_path: str,
        repo_name: str,
    ) -> tuple[List[Symbol], List[str]]:
        symbols: List[Symbol] = []
        imports: List[str] = []

        for node in tree.body:
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}" if module else alias.name)

            # Module-level functions
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    self._make_symbol(
                        node=node,
                        kind="function",
                        file_path=file_path,
                        repo_name=repo_name,
                        parent=None,
                    )
                )

            # Classes + methods
            elif isinstance(node, ast.ClassDef):
                class_sym = self._make_symbol(
                    node=node,
                    kind="class",
                    file_path=file_path,
                    repo_name=repo_name,
                    parent=None,
                )
                symbols.append(class_sym)

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(
                            self._make_symbol(
                                node=item,
                                kind="method",
                                file_path=file_path,
                                repo_name=repo_name,
                                parent=class_sym.qualified_name,
                            )
                        )

        return symbols, imports

    def _make_symbol(
        self,
        node: ast.AST,
        kind: str,
        file_path: str,
        repo_name: str,
        parent: Optional[str],
    ) -> Symbol:
        name = getattr(node, "name", "unknown")
        if parent:
            qualified = f"{parent}.{name}"
        else:
            # module-level: file_path without .py + name
            module_part = file_path.replace("/", ".").removesuffix(".py")
            qualified = f"{module_part}.{name}" if module_part else name

        node_id = NodeID.from_parts(repo_name, kind, qualified)

        docstring = ast.get_docstring(node)
        decorators = []
        if hasattr(node, "decorator_list"):
            for d in node.decorator_list:
                try:
                    decorators.append(ast.unparse(d))
                except Exception:
                    decorators.append("decorator")

        span = SourceSpan(
            start_line=getattr(node, "lineno", 1),
            end_line=getattr(node, "end_lineno", getattr(node, "lineno", 1)),
        )

        return Symbol(
            node_id=node_id,
            name=name,
            qualified_name=qualified,
            kind=kind,  # type: ignore
            language="python",
            file_path=file_path,
            span=span,
            docstring=docstring,
            decorators=decorators,
            parent_qualified_name=parent,
        )