from typing import List, Optional
from langchain_core.documents import Document
from core.llm import get_llm


def structural_bonus(
    doc: Document,
    prefer_paths: Optional[List[str]] = None,
    prefer_symbols: Optional[List[str]] = None,
    changed_files: Optional[List[str]] = None,
) -> float:
    """Compute structural score bonus for a document based on paths and symbols."""
    meta = getattr(doc, "metadata", {}) or {}
    path = str(meta.get("path") or meta.get("file") or "").replace("\\", "/").lstrip("./")
    text = getattr(doc, "page_content", "") or ""
    symbols_in_meta = meta.get("symbols") or []
    if isinstance(symbols_in_meta, str):
        symbols_in_meta = [symbols_in_meta]

    bonus = 0.0
    all_target_paths = [
        p.replace("\\", "/").lstrip("./")
        for p in (prefer_paths or []) + (changed_files or [])
        if p
    ]

    # Exact path match or directory/package match
    matched_exact = False
    for p in all_target_paths:
        if path == p or path.endswith("/" + p) or p.endswith("/" + path):
            bonus += 3.0
            matched_exact = True
            break

    if not matched_exact:
        for p in all_target_paths:
            p_parts = [part for part in p.split("/") if part]
            path_parts = [part for part in path.split("/") if part]
            if len(p_parts) > 1 and len(path_parts) > 1 and path_parts[0] == p_parts[0]:
                bonus += 1.5
                break

    # Symbol match in chunk or metadata
    for s in prefer_symbols or []:
        if not s:
            continue
        if s in symbols_in_meta or s in text:
            bonus += 2.0

    # Penalize obvious distractors when prefer_paths is specific
    if prefer_paths and path:
        norm_prefs = [p.replace("\\", "/").lstrip("./") for p in prefer_paths if p]
        is_prefer_path = any(
            path == p or path.endswith("/" + p) or p.endswith("/" + path)
            for p in norm_prefs
        )
        if not is_prefer_path:
            if "install" in path and any("build" in p for p in norm_prefs):
                bonus -= 2.0
            elif "export" in path and any("build" in p for p in norm_prefs):
                bonus -= 1.0
            elif "security" in path and any("build" in p for p in norm_prefs):
                bonus -= 1.0

    return bonus


class Reranker:
    """Reranker combining structural bonuses with relevance scoring."""

    def structural_bonus(
        self,
        doc: Document,
        prefer_paths: Optional[List[str]] = None,
        prefer_symbols: Optional[List[str]] = None,
        changed_files: Optional[List[str]] = None,
    ) -> float:
        return structural_bonus(doc, prefer_paths, prefer_symbols, changed_files)

    def rerank(
        self,
        query: str,
        docs: List[Document],
        top_k: int = 6,
        prefer_paths: Optional[List[str]] = None,
        prefer_symbols: Optional[List[str]] = None,
        changed_files: Optional[List[str]] = None,
        k: Optional[int] = None,
    ) -> List[Document]:
        if k is not None:
            top_k = k
        if not docs:
            return []

        # Deduplicate docs by path + content preview
        unique_docs: List[Document] = []
        seen = set()
        for d in docs:
            p = str((getattr(d, "metadata", {}) or {}).get("path") or "").replace("\\", "/").lstrip("./")
            c = (getattr(d, "page_content", "") or "")[:120]
            key = (p, c)
            if key not in seen:
                seen.add(key)
                unique_docs.append(d)

        # Compute combined score: structural bonus + base rank
        scored_docs = []
        for i, doc in enumerate(unique_docs):
            sb = self.structural_bonus(
                doc,
                prefer_paths=prefer_paths,
                prefer_symbols=prefer_symbols,
                changed_files=changed_files,
            )
            # Base semantic score from doc metadata or reciprocal rank
            base_score = float((getattr(doc, "metadata", {}) or {}).get("score", 0.0))
            if base_score == 0.0:
                base_score = 1.0 / (1.0 + i * 0.1)

            total_score = sb + 1.0 * base_score
            if getattr(doc, "metadata", None) is not None:
                doc.metadata["rerank_score"] = total_score
                doc.metadata["structural_bonus"] = sb
            scored_docs.append((total_score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored_docs[:top_k]]