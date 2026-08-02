"""
CodeTurtle v1 smoke checks.

Prerequisites:
  - Repo already indexed: python -m cli.main add-repo Owner/Repo
  - Ollama optional (this smoke does NOT call agents/LLMs)
  - Qdrant data present under your configured path
  - Neo4j optional

Usage:
  python -m tests.verification.smoke_v1
  python -m tests.verification.smoke_v1 Graphify-Labs/graphify
"""

from __future__ import annotations

import sys
from pathlib import Path

# project root on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_REPO = "Graphify-Labs/graphify"


def _ok(name: str, detail: str = "") -> None:
    print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))


def _fail(name: str, detail: str) -> None:
    print(f"  FAIL  {name} — {detail}")


def _warn(name: str, detail: str) -> None:
    print(f"  WARN  {name} — {detail}")


def check_repository_model(repo_name: str) -> bool:
    print("\n=== 1. Repository Intelligence ===")
    try:
        from core.repository_persistence import RepositoryPersistence

        persistence = RepositoryPersistence(repo_name)
        model = persistence.load_repository_model()
        if model is None:
            _fail("repository_model", "load returned None — run add-repo first")
            return False

        total = getattr(model, "total_files", None) or len(getattr(model, "files", []) or [])
        if total <= 0:
            _fail("total_files", f"got {total}")
            return False
        _ok("total_files", str(total))

        files = getattr(model, "files", []) or []
        with_content = sum(1 for f in files if (getattr(f, "content", None) or "").strip())
        if with_content <= 0:
            _fail("file content", "no FileModel.content populated")
            return False
        _ok("file content", f"{with_content}/{len(files)} non-empty")

        sym_idx = getattr(model, "symbol_index", None) or {}
        _ok("symbol_index", f"{len(sym_idx)} entries")

        model_path = persistence.workspace / "repository_model.json"
        if not model_path.exists():
            _fail("repository_model.json", f"missing at {model_path}")
            return False
        _ok("repository_model.json", str(model_path))
        return True
    except Exception as e:
        _fail("repository_model", repr(e))
        return False


def check_qdrant(repo_name: str) -> bool:
    print("\n=== 2. Qdrant knowledge base ===")
    collection = repo_name.replace("/", "_")
    try:
        from core.knowledge_base import KnowledgeBase

        kb = KnowledgeBase(collection)
        client = kb.client
        names = [c.name for c in client.get_collections().collections]
        if collection not in names:
            _fail("collection exists", f"{collection} not in {names}")
            return False
        _ok("collection exists", collection)

        info = client.get_collection(collection)
        points = getattr(info, "points_count", None)
        if points is None and hasattr(info, "points_count"):
            points = info.points_count
        # qdrant-client variants
        if points is None:
            points = getattr(getattr(info, "config", None), "params", None)
            points = info.points_count if hasattr(info, "points_count") else 0

        count = int(info.points_count)
        if count <= 0:
            _fail("points_count", f"{count} — re-run add-repo with force")
            return False
        _ok("points_count", str(count))

        # smoke similarity
        docs = kb.similarity_search("main function class import", k=3)
        if not docs:
            _fail("similarity_search", "returned 0 documents")
            return False
        _ok("similarity_search", f"{len(docs)} docs")
        return True
    except Exception as e:
        _fail("qdrant", repr(e))
        return False


def check_neo4j(repo_name: str) -> bool:
    print("\n=== 3. Neo4j graph (optional) ===")
    try:
        from core.repository_intelligence.graph.store import GraphStore

        store = GraphStore()
        if not store.health_check():
            _warn("neo4j", "not reachable — skip")
            return True

        driver = store.connect()
        with driver.session() as session:
            files = session.run(
                "MATCH (r:Repository {name: $repo})-[:CONTAINS]->(f:File) RETURN count(f) AS c",
                repo=repo_name,
            ).single()
            n_files = files["c"] if files else 0

            calls = session.run("MATCH ()-[r:CALLS]->() RETURN count(r) AS c").single()
            n_calls = calls["c"] if calls else 0

            imports = session.run("MATCH ()-[r:IMPORTS]->() RETURN count(r) AS c").single()
            n_imports = imports["c"] if imports else 0

        if n_files <= 0:
            _warn("graph files", "0 File nodes for this repo — graph sync may have been skipped")
        else:
            _ok("graph files", str(n_files))

        _ok("IMPORTS edges (db)", str(n_imports))
        _ok("CALLS edges (db)", str(n_calls))

        try:
            store.close()
        except Exception:
            pass
        return True
    except Exception as e:
        _warn("neo4j", f"skip: {e}")
        return True


def check_retrieval(repo_name: str) -> bool:
    print("\n=== 4. HybridRetriever ===")
    collection = repo_name.replace("/", "_")
    try:
        from core.knowledge_base import KnowledgeBase
        from core.hybrid_retriever import HybridRetriever

        kb = KnowledgeBase(collection)
        graph_queries = None
        try:
            from core.repository_intelligence.graph.queries import GraphQueries
            graph_queries = GraphQueries()
        except Exception as e:
            _warn("GraphQueries", str(e))

        retriever = HybridRetriever(
            repo_name,
            kb=kb,
            graph_queries=graph_queries,
            require_kb=True,
        )

        query = "extract build graph repository intelligence imports calls"
        package = retriever.retrieve(
            query=query,
            pr_understanding={},
            files_changed=[],
            k=6,
            use_calls=True,
            fail_if_empty=True,
        )

        n = len(getattr(package, "evidences", None) or [])
        if n <= 0:
            # some packages only expose summary
            summary = getattr(package, "summary", None) or ""
            if not summary.strip():
                _fail("retrieve", "EvidencePackage empty")
                return False
            _ok("retrieve", "summary present, evidences list empty")
        else:
            _ok("retrieve", f"{n} evidences")
        return True
    except RuntimeError as e:
        _fail("retrieve (expected fail-loud path)", str(e))
        return False
    except Exception as e:
        _fail("retrieve", repr(e))
        return False


def check_build_evidence_node(repo_name: str) -> bool:
    print("\n=== 5. build_evidence_package node ===")
    try:
        from core.agents import build_evidence_package

        state = {
            "repo": repo_name,
            "title": "Smoke test PR: repository extract and build",
            "body": "Validates hybrid retrieval and evidence packaging for v1.",
            "files_changed": [],
            "pr_understanding": {},
            "pr_analysis": {},
        }

        out = build_evidence_package(state)
        if "evidence_package" not in out:
            _fail("evidence_package key", f"keys={list(out.keys())}")
            return False
        _ok("evidence_package key")

        ctx = out.get("context_from_kb") or ""
        if not str(ctx).strip():
            _fail("context_from_kb", "empty")
            return False
        _ok("context_from_kb", f"{len(ctx)} chars")
        return True
    except RuntimeError as e:
        _fail("build_evidence_package", str(e))
        return False
    except Exception as e:
        _fail("build_evidence_package", repr(e))
        return False


def main() -> int:
    repo = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO
    print(f"CodeTurtle v1 smoke — repo={repo}")

    results = [
        check_repository_model(repo),
        check_qdrant(repo),
        check_neo4j(repo),
        check_retrieval(repo),
        check_build_evidence_node(repo),
    ]

    print("\n=== Summary ===")
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} checks passed")
    # neo4j always returns True (warn-only); treat as soft
    if not all(results):
        print("SMOKE FAILED")
        return 1
    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())