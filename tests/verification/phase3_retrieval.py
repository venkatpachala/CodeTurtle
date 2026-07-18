from core.hybrid_retriever import HybridRetriever
from core.knowledge_base import KnowledgeBase

def verify_retrieval():
    """Phase 3 — Retrieval Verification"""

    print("=== Retrieval Verification ===")

    kb = KnowledgeBase("NousResearch_hermes-agent")
    retriever = HybridRetriever("NousResearch/hermes-agent", kb=kb)

    query = "recover stale model and cache state"

    evidence = retriever.retrieve(query=query, pr_understanding={}, k=8)

    print(f"Retrieved chunks: {len(evidence.evidences)}")
    print(f"Relevant files: {[e.path for e in evidence.evidences[:3]]}")

    if len(evidence.evidences) > 0:
        print("Retrieval PASSED")
    else:
        print("Retrieval FAILED")