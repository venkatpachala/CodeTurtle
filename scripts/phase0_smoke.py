"""
Phase 0 smoke test for Repository Intelligence v1.
"""

from pathlib import Path
from core.repository_intelligence.compiler.compiler import RepositoryCompiler
from core.repository_intelligence.graph.store import GraphStore


def main():
    # Point to an already-cloned repo under repos/
    repo_name = "Graphify-Labs/graphify"
    local_path = Path("repos") / repo_name.replace("/", "_")

    if not local_path.exists():
        print(f"Repo not found at {local_path}. Run add-repo first.")
        return

    print("=== Phase 0: RepositorySnapshot ===")
    compiler = RepositoryCompiler(repo_name=repo_name, local_path=str(local_path))
    snapshot = compiler.compile()

    print(f"Repo:        {snapshot.repo_name}")
    print(f"Files:       {snapshot.total_files}")
    print(f"Languages:   {snapshot.languages}")
    print(f"Sample files:")
    for f in snapshot.files[:8]:
        print(f"  - {f.path} ({f.language}, {f.line_count} lines)")

    print("\n=== Phase 0: Neo4j Health ===")
    store = GraphStore()
    ok = store.health_check()
    print(f"Neo4j reachable: {ok}")
    if ok:
        store.ensure_constraints()
    store.close()

    print("\nPhase 0 smoke test complete.")


if __name__ == "__main__":
    main()