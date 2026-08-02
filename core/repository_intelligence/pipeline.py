from pathlib import Path
from typing import List, Optional, Dict, Set, Tuple
import os
import ast
from datetime import datetime

from core.repository_model import FileModel, RepositoryModel, Symbol
from core.knowledge_base import KnowledgeBase
from core.repository_persistence import RepositoryPersistence
from core.repository_analyzer import RepositoryAnalyzer
from core.repository_indexer import RepositoryIndexer
from core.repository_intelligence.call_extractor import CallExtractor


class RepositoryIntelligence:
    def __init__(self, repo_path: str, repo_name: str):
        self.repo_path = Path(repo_path)
        self.repo_name = repo_name
        self.repository_model = RepositoryModel(repo_name=repo_name)
        self.persistence = RepositoryPersistence(repo_name)

    def index_repository(self, force: bool = False) -> RepositoryModel:
        """
        RI write path:
          scan → metadata/AST → analyze → persist
          → Qdrant embed → Neo4j (Files, Symbols, IMPORTS, CALLS)
        """
        print(f"[RepositoryIntelligence] Indexing {self.repo_name}...")

        current_files = list(self._scan_files())

        file_models = []
        for file_path in current_files:
            if force or self._should_reindex(file_path):
                fm = self._extract_file_metadata(file_path)
                if fm:
                    file_models.append(fm)

        self.repository_model.files = file_models
        self.repository_model.total_files = len(file_models)
        self.repository_model.indexed_at = datetime.now()
        self.repository_model.symbol_index = {}
        self._build_symbol_index()

        analyzer = RepositoryAnalyzer(self.repository_model)
        analyzer.analyze()

        self.persistence.save_repository_model(self.repository_model)
        self._embed_and_store(file_models, force=force)
        self._sync_neo4j_graph()

        print(f"[RepositoryIntelligence] Indexed {len(file_models)} files (clean).")
        return self.repository_model

    def _should_reindex(self, file_path: Path) -> bool:
        model_path = self.persistence.workspace / "repository_model.json"
        if not model_path.exists():
            return True
        return file_path.stat().st_mtime > model_path.stat().st_mtime

    def _scan_files(self) -> List[Path]:
        allowed_extensions = {".py", ".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml"}
        excluded_dirs = {"node_modules", ".git", "__pycache__", "build", "dist", ".venv", "venv"}

        files: List[Path] = []
        for root, dirs, filenames in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            for filename in filenames:
                if any(filename.endswith(ext) for ext in allowed_extensions):
                    full_path = Path(root) / filename
                    if full_path.stat().st_size < 500_000:
                        files.append(full_path)
        return files

    def _extract_file_metadata(self, file_path: Path) -> Optional[FileModel]:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            extension = file_path.suffix.lower()
            language = self._detect_language(extension)
            rel = str(file_path.relative_to(self.repo_path)).replace("\\", "/")

            file_model = FileModel(
                path=rel,
                language=language,
                extension=extension,
                size_bytes=len(content.encode("utf-8", errors="ignore")),
                content=content,
                preview=content[:600] + "..." if len(content) > 600 else content,
                line_count=len(content.splitlines()),
                last_modified=datetime.fromtimestamp(file_path.stat().st_mtime),
            )

            if extension == ".py":
                self._parse_python_ast(file_path, content, file_model)

            return file_model
        except Exception as e:
            print(f"Warning: Could not process {file_path}: {e}")
            return None

    def _parse_python_ast(self, file_path: Path, content: str, file_model: FileModel):
        try:
            tree = ast.parse(content, filename=str(file_path))

            imports: List[str] = []
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name:
                            imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
            file_model.imports = sorted(set(imports))

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    file_model.symbols.append(
                        Symbol(
                            name=node.name,
                            type="class",
                            line=node.lineno,
                            docstring=ast.get_docstring(node),
                        )
                    )
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            file_model.symbols.append(
                                Symbol(
                                    name=child.name,
                                    type="method",
                                    line=child.lineno,
                                    docstring=ast.get_docstring(child),
                                )
                            )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    file_model.symbols.append(
                        Symbol(
                            name=node.name,
                            type="function",
                            line=node.lineno,
                            docstring=ast.get_docstring(node),
                        )
                    )
        except SyntaxError:
            pass

    def _detect_language(self, extension: str) -> str:
        mapping = {
            ".py": "Python",
            ".md": "Markdown",
            ".rst": "reStructuredText",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".json": "JSON",
            ".toml": "TOML",
        }
        return mapping.get(extension, "Unknown")

    def _build_symbol_index(self):
        for fm in self.repository_model.files:
            for symbol in fm.symbols:
                key = f"{fm.path}::{symbol.name}"
                self.repository_model.symbol_index[key] = symbol

    def _embed_and_store(self, file_models: List[FileModel], force: bool = False):
        if not file_models:
            return

        indexer = RepositoryIndexer(self.repository_model)
        documents = indexer.to_documents()

        for d in documents:
            if d.metadata and "path" in d.metadata:
                d.metadata["path"] = str(d.metadata["path"]).replace("\\", "/")

        kb = KnowledgeBase(self.repo_name.replace("/", "_"))

        if force:
            kb.recreate_collection()
            print("[RepositoryIntelligence] Qdrant collection rebuilt (full re-index).")

        before = kb.client.get_collection(kb.collection_name).points_count
        kb.add_documents(documents)
        after = kb.client.get_collection(kb.collection_name).points_count

        print(
            f"[RepositoryIntelligence] Stored {len(documents)} chunks "
            f"(points {before} → {after})."
        )

    def _sync_neo4j_graph(self):
        """Write Files, Symbols, IMPORTS, and CALLS into Neo4j."""
        try:
            from core.repository_intelligence.graph.store import GraphStore
        except ImportError as e:
            print(f"[RepositoryIntelligence] Graph package missing, skip Neo4j: {e}")
            return

        store = GraphStore()
        if not store.health_check():
            print("[RepositoryIntelligence] Neo4j not reachable — skip graph sync.")
            return

        driver = store.connect()
        repo = self.repo_name
        files = self.repository_model.files

        path_set: Set[str] = {fm.path.replace("\\", "/") for fm in files}
        module_to_path: Dict[str, str] = {}
        for p in path_set:
            if not p.endswith(".py"):
                continue
            mod = p[:-3].replace("/", ".")
            module_to_path[mod] = p
            if p.endswith("/__init__.py"):
                pkg = p[: -len("/__init__.py")].replace("/", ".")
                module_to_path[pkg] = p

        def resolve_import(imp: str) -> Optional[str]:
            imp = (imp or "").strip()
            if not imp:
                return None
            if imp in module_to_path:
                return module_to_path[imp]
            parts = imp.split(".")
            for i in range(len(parts), 0, -1):
                cand = ".".join(parts[:i])
                if cand in module_to_path:
                    return module_to_path[cand]
            return None

        try:
            with driver.session() as session:
                session.run(
                    """
                    MATCH (r:Repository {name: $repo})
                    OPTIONAL MATCH (r)-[:CONTAINS*]->(n)
                    DETACH DELETE r, n
                    """,
                    repo=repo,
                )
                session.run(
                    """
                    MERGE (r:Repository {name: $repo})
                    SET r.indexed_at = $ts
                    """,
                    repo=repo,
                    ts=datetime.now().isoformat(),
                )

                for fm in files:
                    path = fm.path.replace("\\", "/")
                    session.run(
                        """
                        MATCH (r:Repository {name: $repo})
                        MERGE (f:File {path: $path})
                        SET f.language = $language,
                            f.extension = $extension,
                            f.line_count = $line_count
                        MERGE (r)-[:CONTAINS]->(f)
                        """,
                        repo=repo,
                        path=path,
                        language=fm.language,
                        extension=fm.extension,
                        line_count=fm.line_count,
                    )

                sym_count = 0
                for fm in files:
                    path = fm.path.replace("\\", "/")
                    for sym in fm.symbols:
                        session.run(
                            """
                            MATCH (f:File {path: $path})
                            MERGE (s:Symbol {qualified_name: $qn})
                            SET s.name = $name,
                                s.kind = $kind,
                                s.line = $line
                            MERGE (f)-[:CONTAINS]->(s)
                            """,
                            path=path,
                            qn=f"{path}::{sym.name}",
                            name=sym.name,
                            kind=sym.type,
                            line=sym.line,
                        )
                        sym_count += 1

                import_count = 0
                for fm in files:
                    src = fm.path.replace("\\", "/")
                    for imp in fm.imports or []:
                        dst = resolve_import(imp)
                        if not dst or dst == src:
                            continue
                        session.run(
                            """
                            MATCH (a:File {path: $src})
                            MATCH (b:File {path: $dst})
                            MERGE (a)-[:IMPORTS]->(b)
                            """,
                            src=src,
                            dst=dst,
                        )
                        import_count += 1

                call_edges = self._resolve_calls()
                call_count = 0
                for caller_qn, callee_qn, line in call_edges:
                    result = session.run(
                        """
                        MATCH (a:Symbol {qualified_name: $caller})
                        MATCH (b:Symbol {qualified_name: $callee})
                        MERGE (a)-[r:CALLS]->(b)
                        SET r.line = $line
                        RETURN 1 AS ok
                        """,
                        caller=caller_qn,
                        callee=callee_qn,
                        line=line,
                    )
                    if result.single() is not None:
                        call_count += 1

                print(
                    f"[RepositoryIntelligence] Neo4j sync OK — "
                    f"files={len(files)} symbols={sym_count} "
                    f"import_edges≈{import_count} calls≈{call_count}"
                )
        except Exception as e:
            print(f"[RepositoryIntelligence] Neo4j sync failed: {e}")
        finally:
            try:
                store.close()
            except Exception:
                pass

    def _resolve_calls(self) -> List[Tuple[str, str, int]]:
        """
        Precision-first CALLS resolution:
          - skip attribute calls (obj.get / d.items) — main noise source
          - do not resolve targets under worked/
          - same-file → accept
          - unique name → accept
          - single import-preferred → accept
          - else skip (never candidates[0])
        """
        if not self.repository_model.symbol_index:
            self._build_symbol_index()

        by_name: Dict[str, List[str]] = {}
        for qn, sym in self.repository_model.symbol_index.items():
            path = qn.split("::")[0].replace("\\", "/")
            if path.startswith("worked/"):
                continue
            by_name.setdefault(sym.name, []).append(qn)

        edges: List[Tuple[str, str, int]] = []
        seen: Set[Tuple[str, str]] = set()
        stats = {
            "sites": 0,
            "skipped_attr": 0,
            "skipped_ambiguous": 0,
            "skipped_no_candidate": 0,
            "accepted_same_file": 0,
            "accepted_unique": 0,
            "accepted_import": 0,
        }

        for fm in self.repository_model.files:
            if getattr(fm, "language", "") != "Python":
                continue
            content = getattr(fm, "content", "") or ""
            if not content:
                continue

            path = fm.path.replace("\\", "/")
            if path.startswith("worked/"):
                continue

            try:
                tree = ast.parse(content, filename=path)
            except SyntaxError:
                continue

            try:
                call_sites = CallExtractor(path).extract(tree).calls
            except Exception:
                call_sites = self._extract_calls_inline(tree, path)

            for cs in call_sites:
                stats["sites"] += 1

                if getattr(cs, "is_attribute", False):
                    stats["skipped_attr"] += 1
                    continue

                caller_qn = f"{path}::{cs.caller_name}"
                if caller_qn not in self.repository_model.symbol_index:
                    continue

                candidates = by_name.get(cs.callee_name, [])
                if not candidates:
                    stats["skipped_no_candidate"] += 1
                    continue

                same_file = [c for c in candidates if c.startswith(path + "::")]
                if same_file:
                    callee_qn = same_file[0]
                    stats["accepted_same_file"] += 1
                elif len(candidates) == 1:
                    callee_qn = candidates[0]
                    stats["accepted_unique"] += 1
                else:
                    preferred = []
                    for c in candidates:
                        c_mod = c.split("::")[0].replace("/", ".")
                        if any(
                            c_mod == imp or c_mod.startswith(imp + ".")
                            for imp in (fm.imports or [])
                        ):
                            preferred.append(c)
                    if len(set(preferred)) == 1:
                        callee_qn = preferred[0]
                        stats["accepted_import"] += 1
                    else:
                        stats["skipped_ambiguous"] += 1
                        continue

                if caller_qn == callee_qn:
                    continue
                key = (caller_qn, callee_qn)
                if key in seen:
                    continue
                seen.add(key)
                edges.append((caller_qn, callee_qn, cs.call_line))

        print(
            f"[CALLS] sites={stats['sites']} edges={len(edges)} "
            f"same_file={stats['accepted_same_file']} "
            f"unique={stats['accepted_unique']} "
            f"import={stats['accepted_import']} "
            f"skip_attr={stats['skipped_attr']} "
            f"skip_ambiguous={stats['skipped_ambiguous']} "
            f"skip_no_cand={stats['skipped_no_candidate']}"
        )
        return edges

    def _extract_calls_inline(self, tree: ast.AST, path: str):
        """Fallback if CallExtractor import fails."""
        from dataclasses import dataclass
        from typing import List

        @dataclass
        class CallSite:
            caller_name: str
            caller_line: int
            callee_name: str
            call_line: int
            is_attribute: bool = False

        calls: List[CallSite] = []
        stack: List[tuple] = []

        class V(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef):
                stack.append((node.name, node.lineno))
                self.generic_visit(node)
                stack.pop()

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                stack.append((node.name, node.lineno))
                self.generic_visit(node)
                stack.pop()

            def visit_Call(self, node: ast.Call):
                if stack:
                    caller_name, caller_line = stack[-1]
                    callee, is_attr = None, False
                    if isinstance(node.func, ast.Name):
                        callee = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        callee = node.func.attr
                        is_attr = True
                    if callee:
                        calls.append(
                            CallSite(
                                caller_name=caller_name,
                                caller_line=caller_line,
                                callee_name=callee,
                                call_line=getattr(node, "lineno", 0),
                                is_attribute=is_attr,
                            )
                        )
                self.generic_visit(node)

        V().visit(tree)
        return calls