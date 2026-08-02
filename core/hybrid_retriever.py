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


class HybridRetriever:
    def __init__(
        self,
        repo_name: str,
        kb: Optional[KnowledgeBase] = None,
        graph_queries: Optional[Any] = None,  # GraphQueries instance or None
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
        k: int = 8,
        use_calls: bool = True,
        fail_if_empty: bool = True,
    ) -> EvidencePackage:
        """Vector + symbol + capped IMPORTS/CALLS expansion, then rerank."""
        print(f"[HybridRetriever] Querying collection: {self.repo_name.replace('/', '_')}")
        pr_understanding = pr_understanding or {}
        files_changed = [p.replace("\\", "/") for p in (files_changed or []) if p]

        # --- 1. Vector search ---
        vector_docs = self.kb.similarity_search(query, k=k * 2)
        print(f"[HybridRetriever] Vector search returned {len(vector_docs)} documents")

        # --- 2. Symbol search ---
        symbol_docs = self._symbol_search(query, k=max(1, k // 2))

        all_docs = list(vector_docs) + list(symbol_docs)

        # --- 3. Seed paths (PR files first) ---
        seed_paths = self._collect_seed_paths(
            docs=all_docs,
            pr_understanding=pr_understanding,
            files_changed=files_changed,
        )

        # --- 4. Graph expansion: IMPORTS + optional filtered CALLS ---
        graph_docs: List[Document] = []
        expanded: List[str] = []

        if self._graph and seed_paths:
            try:
                if hasattr(self._graph, "expand_paths"):
                    expanded.extend(self._graph.expand_paths(seed_paths, limit_per=8))
                elif hasattr(self._graph, "expand_imports"):
                    expanded.extend(self._graph.expand_imports(seed_paths, limit=15))
            except Exception as e:
                print(f"[HybridRetriever] IMPORTS expand skipped: {e}")

            if use_calls and hasattr(self._graph, "expand_calls"):
                try:
                    expanded.extend(
                        self._graph.expand_calls(
                            seed_paths,
                            limit=10,
                            exclude_prefixes=("tests/", "worked/"),
                            max_callee_degree=150,
                        )
                    )
                except Exception as e:
                    print(f"[HybridRetriever] CALLS expand skipped: {e}")

            expanded = [
                p.replace("\\", "/")
                for p in expanded
                if p
                and not p.startswith("tests/")
                and not p.startswith("worked/")
            ]
            expanded = list(dict.fromkeys(expanded))[:12]
            self._last_graph_expansion = expanded

            print(
                f"[HybridRetriever] Graph expansion: "
                f"{len(seed_paths)} seeds → {len(expanded)} paths (capped)"
            )

            existing: Set[str] = {
                str((d.metadata or {}).get("path", "")).replace("\\", "/")
                for d in all_docs
                if (d.metadata or {}).get("path")
            }
            # Prefer fetching changed files even if already partially present
            priority = [p for p in files_changed if p not in existing]
            rest = [p for p in expanded if p not in existing and p not in priority]
            graph_docs = self._docs_for_paths(
                priority + rest,
                exclude=set(),
                max_docs=8,
            )
            all_docs.extend(graph_docs)
        else:
            self._last_graph_expansion = []

        # --- 5. Prefer docs whose path is in files_changed before rerank ---
        all_docs = self._prefer_changed_files(all_docs, files_changed)

        # --- 6. Rerank ---
        ranked_docs = self.reranker.rerank(query, all_docs, top_k=k)

        print(
            f"[HybridRetriever] Retrieved {len(vector_docs)} vector + "
            f"{len(symbol_docs)} symbol + {len(graph_docs)} graph → "
            f"reranked to {len(ranked_docs)} documents"
        )

        if fail_if_empty and not ranked_docs:
            raise RuntimeError(
                f"Knowledge base retrieval returned no context for {self.repo_name}. "
                "Re-run: python -m cli.main add-repo <owner/repo>"
            )

        # --- 7. Evidence package ---
        package = ContextBuilder.build(
            query=query,
            pr_understanding=pr_understanding,
            documents=ranked_docs,
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

    def retrieve_multi(
        self,
        queries: List[RetrievalQuery],
        k_per_query: int = 6,
        max_total: int = 12,
        pr_understanding: dict = None,
        files_changed: List[str] | None = None,
    ) -> EvidencePackage:
        print(f"[HybridRetriever] Multi-query retrieval with {len(queries)} queries")
        pr_understanding = pr_understanding or {}
        files_changed = files_changed or []

        all_docs = []
        for q in queries:
            package = self.retrieve(
                q.text,
                pr_understanding=pr_understanding,
                files_changed=files_changed,
                k=k_per_query,
                fail_if_empty=False,  # empty single query OK; final check below
            )
            docs = package.evidences if hasattr(package, "evidences") else []
            for doc in docs:
                doc.source_query = q.text
                doc.query_category = q.category
                doc.query_weight = q.weight
                all_docs.append(doc)

        unique = {}
        for doc in all_docs:
            file_path = getattr(doc, "path", None) or (doc.metadata or {}).get("path")
            if not file_path:
                continue
            score = getattr(doc, "score", 0) * getattr(doc, "query_weight", 1.0)
            if file_path not in unique or score > unique[file_path][1]:
                unique[file_path] = (doc, score)

        final_docs = [
            doc for doc, _ in sorted(unique.values(), key=lambda x: x[1], reverse=True)
        ][:max_total]

        print(
            f"[HybridRetriever] Retrieved {len(all_docs)} → "
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

    def _prefer_changed_files(
        self, docs: List[Document], files_changed: List[str]
    ) -> List[Document]:
        if not files_changed:
            return docs
        changed = set(files_changed)
        first, rest = [], []
        for d in docs:
            p = str((d.metadata or {}).get("path", "")).replace("\\", "/")
            (first if p in changed else rest).append(d)
        return first + rest

    def _collect_seed_paths(
        self,
        docs: List[Document],
        pr_understanding: dict,
        files_changed: List[str],
    ) -> List[str]:
        seeds: List[str] = []

        for p in files_changed:
            if p:
                seeds.append(p.replace("\\", "/"))

        for key in ("affected_files", "changed_files", "files_changed", "high_risk_files"):
            for p in pr_understanding.get(key) or []:
                if isinstance(p, str) and p:
                    seeds.append(p.replace("\\", "/"))

        for d in docs:
            p = (d.metadata or {}).get("path")
            if p:
                seeds.append(str(p).replace("\\", "/"))

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
            path = path.replace("\\", "/")
            if not path or path in exclude or path in seen:
                continue
            if path.startswith("tests/") or path.startswith("worked/"):
                continue
            seen.add(path)

            doc = self._fetch_by_path(path)
            if doc is not None:
                out.append(doc)
            else:
                out.append(
                    Document(
                        page_content=f"[Graph] Related file: {path}",
                        metadata={"path": path, "retrieval_type": "graph"},
                    )
                )
        return out

    def _fetch_by_path(self, path: str) -> Optional[Document]:
        path = path.replace("\\", "/")
        try:
            if hasattr(self.kb, "get_by_path"):
                hits = self.kb.get_by_path(path, k=1)
                if hits:
                    h = hits[0]
                    meta = dict(h.metadata or {})
                    meta.update({"path": path, "retrieval_type": "graph"})
                    h.metadata = meta
                    return h
        except Exception as e:
            print(f"[HybridRetriever] get_by_path failed for {path}: {e}")
        return None

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