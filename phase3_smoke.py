"""Phase 3: resolve in-repo imports → (:File)-[:IMPORTS]->(:File)."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from core.repository_intelligence.compiler.compiler import RepositoryCompiler
from core.repository_intelligence.graph.store import GraphStore
from core.repository_intelligence.graph.import_resolver import ImportResolver


def main():
    repo_name = "Graphify-Labs/graphify"
    local_path = Path("repos") / repo_name.replace("/", "_")

    if not local_path.exists():
        print(f"Repo not found: {local_path}")
        return

    print("=== Phase 3: Compile ===")
    compiler = RepositoryCompiler(repo_name=repo_name, local_path=str(local_path))
    snapshot = compiler.compile()
    print(
        f"Files: {snapshot.total_files} | "
        f"Symbols: {sum(len(f.symbols) for f in snapshot.files)}"
    )

    # Build {path: [imports]} from snapshot
    file_imports = {}
    paths = []
    for f in snapshot.files:
        path = f.path.replace("\\", "/")
        paths.append(path)
        imports = list(getattr(f, "imports", None) or [])
        file_imports[path] = imports

    with_imports = sum(1 for v in file_imports.values() if v)
    print(f"Files with non-empty imports: {with_imports}")

    print("=== Phase 3: Resolve IMPORTS ===")
    resolver = ImportResolver(paths)
    edges = resolver.resolve_all(file_imports)
    print(f"Resolved IMPORTS edges: {len(edges)}")

    for e in edges[:12]:
        print(f"  {e.source_path} -[:IMPORTS]-> {e.target_path}  ({e.raw_import})")

    print("=== Phase 3: Write to Neo4j ===")
    store = GraphStore()
    if not store.health_check():
        print("Neo4j not reachable. Start the instance first.")
        return

    stats = store.write_imports(edges)
    print("Write stats:", stats)

    driver = store.connect()
    with driver.session() as session:
        total = session.run(
            "MATCH ()-[r:IMPORTS]->() RETURN count(r) AS c"
        ).single()["c"]
        print(f"Total IMPORTS relationships: {total}")

        print("\n=== Sample: top importers ===")
        rows = session.run(
            """
            MATCH (f:File)-[:IMPORTS]->(dep:File)
            RETURN f.path AS src, count(dep) AS n
            ORDER BY n DESC
            LIMIT 10
            """
        )
        for r in rows:
            print(f"  {r['src']}: {r['n']} deps")

        print("\n=== Sample: graphify/cli.py imports ===")
        rows = session.run(
            """
            MATCH (f:File)-[:IMPORTS]->(dep:File)
            WHERE f.path ENDS WITH 'cli.py'
            RETURN f.path AS src, dep.path AS dst
            LIMIT 20
            """
        )
        for r in rows:
            print(f"  {r['src']} -> {r['dst']}")

    store.close()
    print("\nPhase 3 complete.")


if __name__ == "__main__":
    main()