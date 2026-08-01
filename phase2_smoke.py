from pathlib import Path
from core.repository_intelligence.compiler.compiler import RepositoryCompiler
from core.repository_intelligence.graph.store import GraphStore
from core.repository_intelligence.graph.builder import GraphBuilder


def main():
    repo_name = "Graphify-Labs/graphify"
    local_path = Path("repos") / repo_name.replace("/", "_")

    if not local_path.exists():
        print(f"Repo not found: {local_path}")
        return

    print("=== Phase 2: Compile ===")
    compiler = RepositoryCompiler(repo_name=repo_name, local_path=str(local_path))
    snapshot = compiler.compile()
    print(f"Files: {snapshot.total_files} | Symbols: {sum(len(f.symbols) for f in snapshot.files)}")

    print("\n=== Phase 2: Load into Neo4j ===")
    store = GraphStore()
    if not store.health_check():
        print("Neo4j not reachable. Start the instance first.")
        return

    builder = GraphBuilder(store)
    # clear_existing=True on first run so we get a clean graph
    stats = builder.build(snapshot, clear_existing=True)
    print("Graph write stats:", stats)

    # Quick verification query
    driver = store.connect()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (f:File)-[:CONTAINS]->(s:Symbol)
            WHERE f.path = 'graphify/cli.py'
            RETURN s.kind AS kind, s.name AS name, s.qualified_name AS qn
            ORDER BY s.start_line
            LIMIT 15
            """
        )
        print("\n=== Sample from Neo4j (graphify/cli.py) ===")
        for record in result:
            print(f"  {record['kind']:8} {record['name']:25} {record['qn']}")

    store.close()
    print("\nPhase 2 complete.")


if __name__ == "__main__":
    main()