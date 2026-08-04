import re
from typing import List, Optional, Set, TYPE_CHECKING, Any

from langchain_core.documents import Document

from core.knowledge_base import KnowledgeBase
from core.reranker import Reranker
from core.repository_persistence import RepositoryPersistence
from core.context_builder import ContextBuilder
from core.evidence import EvidencePackage
from core.query_builder import RetrievalQuery

try:
    from core.repository_intelligence.graph.queries import GraphQueries
except ImportError:
    GraphQueries = None  # type: ignore

if TYPE_CHECKING:
    from core.repository_intelligence.graph.queries import GraphQueries as GraphQueriesType
else:
    GraphQueriesType = Any


def diff_chunks_for_paths(full_diff: str, paths: Optional[List[str]] = None) -> List[Document]:
    """Extract unified diff hunks for target paths into Document objects."""
    if not full_diff or not full_diff.strip():
        return []

    norm_paths = {p.replace("\\", "/").lstrip("./") for p in (paths or []) if p}
    docs: List[Document] = []

    # Split by file patches
    file_sections = re.split(r"(?=^---\s+|^diff --git\s+)", full_diff, flags=re.MULTILINE)
    for section in file_sections:
        section = section.strip()
        if not section:
            continue
        m = re.search(r"^\+\+\+\s+(?:[b/])?([^\s\n]+)", section, flags=re.MULTILINE)
        if not m:
            m = re.search(r"^---\s+(?:[a/])?([^\s\n]+)", section, flags=re.MULTILINE)
        if not m:
            continue

        raw_path = m.group(1).lstrip("b/").lstrip("a/").replace("\\", "/").lstrip("./")
        if norm_paths and raw_path not in norm_paths:
            if not any(raw_path.endswith(p) or p.endswith(raw_path) for p in norm_paths):
                continue

        symbols = re.findall(r"^[+ ](?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", section, flags=re.MULTILINE)
        consts = re.findall(r"^[+]([A-Z_][A-Z0-9_]*)\s*=", section, flags=re.MULTILINE)
        all_syms = list(dict.fromkeys(symbols + consts))

        docs.append(
            Document(
                page_content=f"Diff for {raw_path}:\n{section[:4000]}",
                metadata={
                    "path": raw_path,
                    "retrieval_type": "diff",
                    "chunk_type": "diff",
                    "symbols": all_syms,
                },
            )
        )
    return docs


def merge_evidence_packages(per_query_docs: list[list[Any]], max_total: int = 18) -> list[Any]:
    """Union + stable rank; prefer higher structural score if present."""
    best: dict[str, tuple[float, Any]] = {}
    for docs in per_query_docs:
        for i, d in enumerate(docs or []):
            meta = getattr(d, "metadata", {}) or {}
            path = meta.get("path", "") or getattr(d, "path", "") or ""
            chunk_i = meta.get("chunk_index", i)
            start = meta.get("start_line", 0) or getattr(d, "start_line", 0) or 0
            content = getattr(d, "page_content", None) or getattr(d, "content", "") or ""
            key = f"{path}::{start}::{chunk_i}::{hash(content[:200])}"
            score = float(meta.get("rerank_score", getattr(d, "score", 0)) or 0) - i * 0.01
            if key not in best or score > best[key][0]:
                best[key] = (score, d)
    ranked = sorted(best.values(), key=lambda x: -x[0])
    return [d for _, d in ranked[:max_total]]


class HybridRetriever:
    def __init__(
        self,
        repo_name: str,
        kb: Optional[KnowledgeBase] = None,
        graph_queries: Optional[Any] = None,
        *,
        require_kb: bool = True,
    ):
        """
        Prefer injecting a shared KnowledgeBase from the review pipeline.
        Set require_kb=False only for isolated scripts.
        """
        self.repo_name = repo_name
        if kb is None:
            if require_kb:
                raise RuntimeError(
                    "HybridRetriever requires a shared KnowledgeBase instance. "
                    "Create one KnowledgeBase in the review pipeline and pass kb=..."
                )
            kb = KnowledgeBase(repo_name.replace("/", "_"))
        self.kb = kb
        self.reranker = Reranker()
        if graph_queries is not None:
            self._graph = graph_queries
        else:
            self._graph = GraphQueries() if GraphQueries else None
        self._last_graph_expansion: List[str] = []

    def retrieve(
        self,
        query: str,
        pr_understanding: dict = None,
        files_changed: List[str] | None = None,
        prefer_paths: List[str] | None = None,
        prefer_symbols: List[str] | None = None,
        full_diff: str | None = None,
        k: int = 8,
        use_calls: bool = True,
        fail_if_empty: bool = True,
        purpose: str | None = None,
    ) -> EvidencePackage:
        """
        Path-forced, exact-symbol-first, diff-injected, constrained-graph hybrid retrieval.
        """
        # Fix 5: Sanitize queries matching anti-patterns like "implementation and usage of %"
        if query.lower().startswith("implementation and usage of "):
            query = query[len("implementation and usage of "):].strip()

        print(f"[HybridRetriever] Querying collection: {self.repo_name.replace('/', '_')}")
        pr_understanding = pr_understanding or {}
        files_changed = [
            p.replace("\\", "/").lstrip("./")
            for p in (files_changed or [])
            if p
        ]
        prefer_paths = [
            p.replace("\\", "/").lstrip("./")
            for p in (prefer_paths or [])
            if p
        ]
        prefer_symbols = [s for s in (prefer_symbols or []) if s]
        k = max(int(k or 8), 1)

        # --- 1. Path-forced retrieval (Fix 1) ---
        forced_docs: List[Document] = []
        for path in prefer_paths:
            hits = self._fetch_by_path_many(path, k=4)
            forced_docs.extend(hits)
        print(f"[HybridRetriever] Path-forced docs for {prefer_paths}: {len(forced_docs)}")

        # --- 2. Deterministic PR Diff Injection (Fix 3) ---
        diff_docs: List[Document] = []
        if full_diff:
            target_diff_paths = list(dict.fromkeys(prefer_paths + files_changed))
            diff_docs = diff_chunks_for_paths(full_diff, target_diff_paths)
            print(f"[HybridRetriever] Injected {len(diff_docs)} diff chunks for {target_diff_paths}")

        # --- 3. Exact Symbol Lookup (Fix 3) ---
        symbol_docs: List[Document] = []
        for sym in prefer_symbols:
            sym_hits = self.lookup_symbol(sym)
            symbol_docs.extend(sym_hits)
        if not symbol_docs and not prefer_symbols:
            symbol_docs = self._symbol_search(query, k=max(1, k // 2))
        print(f"[HybridRetriever] Symbol search returned {len(symbol_docs)} documents")

        # --- 4. Vector Search ---
        vector_docs = self.kb.similarity_search(query, k=max(k * 2, 12))
        print(f"[HybridRetriever] Vector search returned {len(vector_docs)} documents")

        # Initial merge of candidates
        merged = self._dedupe_docs(diff_docs + forced_docs + symbol_docs + list(vector_docs))

        # --- 5. Constrained Graph Expansion (Fix 4) ---
        anchor_paths = list(dict.fromkeys(prefer_paths + files_changed))
        graph_docs = self.graph_expand(
            seeds=merged[:4],
            anchor_paths=anchor_paths,
            max_extra=4,
        )
        merged = self._dedupe_docs(merged + graph_docs)

        # Ensure changed files exist in candidates
        for path in files_changed:
            if not path:
                continue
            already = any(
                str((d.metadata or {}).get("path", "")).replace("\\", "/").lstrip("./") == path
                for d in merged
            )
            if not already:
                extra = self._fetch_by_path_many(path, k=2)
                merged.extend(extra)

        merged = self._dedupe_docs(merged)

        # --- 6. Structural Rerank (Fix 2) ---
        rerank_top = max(k * 2, k)
        ranked_docs = self.reranker.rerank(
            query=query,
            docs=merged,
            top_k=rerank_top,
            prefer_paths=prefer_paths,
            prefer_symbols=prefer_symbols,
            changed_files=files_changed,
        )

        # --- 7. Finalize Docs to k ---
        final_docs = self._finalize_docs(
            ranked=ranked_docs,
            candidates=merged,
            k=k,
            files_changed=files_changed,
            prefer_paths=prefer_paths,
        )

        print(
            f"[HybridRetriever] Finalized {len(final_docs)} documents "
            f"(forced={len(forced_docs)}, diff={len(diff_docs)}, symbol={len(symbol_docs)}, "
            f"vector={len(vector_docs)}, graph={len(graph_docs)})"
        )

        if fail_if_empty and not final_docs:
            raise RuntimeError(
                f"Knowledge base retrieval returned no context for {self.repo_name}. "
                "Re-run: python -m cli.main add-repo <owner/repo>"
            )

        # --- 8. Evidence Package ---
        package = ContextBuilder.build(
            query=query,
            pr_understanding=pr_understanding,
            documents=final_docs,
        )

        seed_paths = self._collect_seed_paths(
            docs=final_docs,
            pr_understanding=pr_understanding,
            files_changed=files_changed,
        )
        dep_context = self._format_dependency_context(seed_paths)
        if dep_context:
            if hasattr(package, "dependency_context"):
                package.dependency_context = dep_context
            if hasattr(package, "extra_context"):
                package.extra_context = (
                    (getattr(package, "extra_context", "") or "") + "\n" + dep_context
                )

        return package

    def lookup_symbol(self, name: str) -> List[Document]:
        """
        Symbol lookup hierarchy (Fix 3):
        1) Qdrant symbol index/metadata filter
        2) RepositoryModel symbol index
        3) Lexical keyword search 'def name'
        4) Similarity vector search
        """
        if not name:
            return []

        # 1) Qdrant metadata.symbols exact match
        if hasattr(self.kb, "search_by_metadata_symbol"):
            hits = self.kb.search_by_metadata_symbol(name, k=4)
            if hits:
                return hits

        # 2) RepositoryModel symbol index
        try:
            persistence = RepositoryPersistence(self.repo_name)
            repo_model = persistence.load_repository_model()
            if repo_model and repo_model.symbol_index:
                hits = []
                for key, symbol in repo_model.symbol_index.items():
                    if symbol.name == name or name == key.split("::")[-1]:
                        path = key.split("::")[0].replace("\\", "/").lstrip("./")
                        doc = self._fetch_by_path(path)
                        if doc:
                            meta = dict(doc.metadata or {})
                            meta.update({"path": path, "symbol": name, "retrieval_type": "symbol"})
                            doc.metadata = meta
                            hits.append(doc)
                            if len(hits) >= 2:
                                break
                if hits:
                    return hits
        except Exception:
            pass

        # 3) Lexical search "def name"
        if hasattr(self.kb, "keyword_search"):
            hits = self.kb.keyword_search(f"def {name}", k=4)
            if hits:
                return hits

        # 4) Vector search
        return self.kb.similarity_search(name, k=4)

    def graph_expand(
        self,
        seeds: List[Document],
        anchor_paths: List[str],
        max_extra: int = 4,
    ) -> List[Document]:
        """
        Constrained graph expansion (Fix 4):
        Only expand neighbors from seeds anchored in anchor_paths or symbol hits.
        Drop unanchored nodes outside package unless caller edge.
        """
        if not self._graph or not seeds:
            return []

        norm_anchors = {p.replace("\\", "/").lstrip("./") for p in anchor_paths if p}
        anchor_pkgs = {p.split("/")[0] for p in norm_anchors if "/" in p}

        # Filter seed paths anchored in target paths or symbols
        valid_seed_paths = []
        for s in seeds:
            spath = str((getattr(s, "metadata", {}) or {}).get("path") or "").replace("\\", "/").lstrip("./")
            if not spath:
                continue
            if spath in norm_anchors or any(spath.endswith(a) or a.endswith(spath) for a in norm_anchors):
                valid_seed_paths.append(spath)
            elif (getattr(s, "metadata", {}) or {}).get("retrieval_type") in ("symbol", "diff"):
                valid_seed_paths.append(spath)

        if not valid_seed_paths:
            for s in seeds[:2]:
                spath = str((getattr(s, "metadata", {}) or {}).get("path") or "").replace("\\", "/").lstrip("./")
                if spath and anchor_pkgs and spath.split("/")[0] in anchor_pkgs:
                    valid_seed_paths.append(spath)

        if not valid_seed_paths:
            self._last_graph_expansion = []
            return []

        valid_seed_paths = list(dict.fromkeys(valid_seed_paths))[:3]
        expanded_paths: List[str] = []
        try:
            if hasattr(self._graph, "expand_paths"):
                expanded_paths = self._graph.expand_paths(valid_seed_paths, limit_per=4)
            elif hasattr(self._graph, "expand_imports"):
                expanded_paths = self._graph.expand_imports(valid_seed_paths, limit=8)
        except Exception as e:
            print(f"[HybridRetriever] graph_expand error: {e}")

        clean_expanded = []
        for p in expanded_paths:
            np = p.replace("\\", "/").lstrip("./")
            if not np or np in norm_anchors or np.startswith("tests/") or np.startswith("worked/"):
                continue
            # Drop nodes outside package of anchors
            if anchor_pkgs and np.split("/")[0] not in anchor_pkgs:
                continue
            clean_expanded.append(np)

        clean_expanded = list(dict.fromkeys(clean_expanded))[:max_extra]
        self._last_graph_expansion = clean_expanded
        return self._docs_for_paths(clean_expanded, max_docs=max_extra)

    def retrieve_multi(
        self,
        queries: List[RetrievalQuery],
        k_per_query: int = 6,
        max_total: int = 18,
        pr_understanding: dict = None,
        files_changed: List[str] | None = None,
    ) -> EvidencePackage:
        print(f"[HybridRetriever] Multi-query retrieval with {len(queries)} queries")
        pr_understanding = pr_understanding or {}
        files_changed = files_changed or []

        per_query_docs = []
        for q in queries:
            package = self.retrieve(
                q.text,
                pr_understanding=pr_understanding,
                files_changed=files_changed,
                k=k_per_query,
                fail_if_empty=False,
            )
            docs = package.evidences if hasattr(package, "evidences") else []
            for doc in docs:
                doc.source_query = q.text
                doc.query_category = q.category
                doc.query_weight = q.weight
            per_query_docs.append(docs)

        final_docs = merge_evidence_packages(per_query_docs, max_total=max_total)

        print(
            f"[HybridRetriever] Retrieved {sum(len(d) for d in per_query_docs)} -> "
            f"deduplicated to {len(final_docs)} documents"
        )

        if not final_docs:
            raise RuntimeError(
                f"Knowledge base multi-retrieval returned no context for {self.repo_name}. "
                "Re-run: python -m cli.main add-repo <owner/repo>"
            )

        return ContextBuilder.build(
            query=" | ".join(q.text for q in queries),
            pr_understanding=pr_understanding,
            documents=final_docs,
        )

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    def _dedupe_docs(self, docs: List[Document]) -> List[Document]:
        seen = set()
        out = []
        for d in docs:
            p = str((getattr(d, "metadata", {}) or {}).get("path") or "").replace("\\", "/").lstrip("./")
            c = (getattr(d, "page_content", "") or "")[:120]
            key = (p, c)
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out

    def _finalize_docs(
        self,
        ranked: Optional[List[Document]],
        candidates: List[Document],
        k: int,
        files_changed: List[str] | None = None,
        prefer_paths: List[str] | None = None,
    ) -> List[Document]:
        """Order from ranked, pad from candidates, ensure prefer_paths and files_changed representation."""
        k = max(int(k or 8), 1)
        files_changed = files_changed or []
        prefer_paths = prefer_paths or []
        target_paths = {
            p.replace("\\", "/").lstrip("./")
            for p in (prefer_paths + files_changed)
            if p
        }

        def path_of(doc: Document) -> str:
            meta = doc.metadata or {}
            return str(meta.get("path") or meta.get("file") or "").replace("\\", "/").lstrip("./")

        def content_key(doc: Document) -> str:
            return (doc.page_content or "")[:160]

        # Build ordered pool
        pool: List[Document] = []
        seen: Set[tuple] = set()

        for d in list(ranked or []) + list(candidates or []):
            key = (path_of(d), content_key(d))
            if key in seen:
                continue
            seen.add(key)
            pool.append(d)

        if not pool:
            return []

        # If prefer_paths specified, ensure prefer_path matches are retained
        if prefer_paths:
            prefs = {p.replace("\\", "/").lstrip("./") for p in prefer_paths if p}
            pref_docs = [
                d for d in pool
                if any(path_of(d) == p or path_of(d).endswith("/" + p) or p.endswith("/" + path_of(d)) for p in prefs)
            ]
            other_docs = [d for d in pool if d not in pref_docs]
            pool = pref_docs + other_docs
        elif target_paths:
            primary = [
                d for d in pool
                if any(path_of(d) == p or path_of(d).endswith("/" + p) or p.endswith("/" + path_of(d)) for p in target_paths)
            ]
            rest = [d for d in pool if d not in primary]
            pool = primary + rest

        return pool[:k]

    def _collect_seed_paths(
        self,
        docs: List[Document],
        pr_understanding: dict,
        files_changed: List[str],
    ) -> List[str]:
        seeds: List[str] = []

        for p in files_changed:
            if p:
                seeds.append(p.replace("\\", "/").lstrip("./"))

        for key in ("affected_files", "changed_files", "files_changed", "high_risk_files"):
            for p in pr_understanding.get(key) or []:
                if isinstance(p, str) and p:
                    seeds.append(p.replace("\\", "/").lstrip("./"))

        for d in docs:
            p = (d.metadata or {}).get("path")
            if p:
                seeds.append(str(p).replace("\\", "/").lstrip("./"))

        return list(dict.fromkeys(seeds))

    def _docs_for_paths(
        self,
        paths: List[str],
        exclude: Set[str] | None = None,
        max_docs: int = 8,
    ) -> List[Document]:
        exclude = exclude or set()
        out: List[Document] = []
        seen: Set[str] = set()

        for path in paths:
            if len(out) >= max_docs:
                break
            path = path.replace("\\", "/").lstrip("./")
            if not path or path in exclude or path in seen:
                continue
            if path.startswith("tests/") or path.startswith("worked/"):
                continue
            seen.add(path)

            hits = self._fetch_by_path_many(path, k=2)
            if hits:
                out.extend(hits)
            else:
                out.append(
                    Document(
                        page_content=f"[Graph] Related file: {path}",
                        metadata={"path": path, "retrieval_type": "graph"},
                    )
                )
        return out[:max_docs]

    def _fetch_by_path(self, path: str) -> Optional[Document]:
        hits = self._fetch_by_path_many(path, k=1)
        return hits[0] if hits else None

    def _fetch_by_path_many(self, path: str, k: int = 2) -> List[Document]:
        path = path.replace("\\", "/").lstrip("./")
        try:
            if hasattr(self.kb, "get_by_path"):
                hits = self.kb.get_by_path(path, k=k)
                out = []
                for h in hits or []:
                    meta = dict(h.metadata or {})
                    meta.update({"path": path, "retrieval_type": meta.get("retrieval_type") or "path"})
                    h.metadata = meta
                    out.append(h)
                return out
        except Exception as e:
            print(f"[HybridRetriever] get_by_path failed for {path}: {e}")
        return []

    def _format_dependency_context(self, seed_paths: List[str]) -> str:
        if not self._graph or not seed_paths:
            return ""
        lines = ["### Repository dependency context (IMPORTS)"]
        for p in seed_paths[:12]:
            deps, imps = [], []
            try:
                if hasattr(self._graph, "direct_imports"):
                    deps = self._graph.direct_imports(p, limit=8)
                if hasattr(self._graph, "importers"):
                    imps = self._graph.importers(p, limit=8)
            except Exception:
                continue
            if not deps and not imps:
                continue
            lines.append(f"\n**{p}**")
            if deps:
                lines.append(f"  imports: {', '.join(deps)}")
            if imps:
                lines.append(f"  imported by: {', '.join(imps)}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _symbol_search(self, query: str, k: int) -> List[Document]:
        try:
            persistence = RepositoryPersistence(self.repo_name)
            repository_model = persistence.load_repository_model()
            if not repository_model or not repository_model.symbol_index:
                return []

            results = []
            q = query.lower()
            for key, symbol in repository_model.symbol_index.items():
                if q in key.lower() or q in symbol.name.lower():
                    results.append(
                        Document(
                            page_content=(
                                f"Symbol: {symbol.name} ({symbol.type})\n"
                                f"File: {key.split('::')[0]}"
                            ),
                            metadata={
                                "path": key.split("::")[0],
                                "symbol": symbol.name,
                                "type": symbol.type,
                                "retrieval_type": "symbol",
                            },
                        )
                    )
                    if len(results) >= k:
                        break
            return results
        except Exception:
            return []

    def _metadata_search(self, query: str, k: int) -> List[Document]:
        return []