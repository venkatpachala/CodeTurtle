"""Phase 3 verification: IMPORTS edges exist and are queryable."""
from core.repository_intelligence.graph.store import GraphStore
from core.repository_intelligence.graph.queries import GraphQueries


def verify_phase3_imports(cli_path: str = "graphify/cli.py") -> bool:
    store = GraphStore()
    if not store.health_check():
        print("FAIL: Neo4j not reachable")
        return False

    driver = store.connect()
    with driver.session() as s:
        total = s.run("MATCH ()-[r:IMPORTS]->() RETURN count(r) AS c").single()["c"]

    print(f"IMPORTS count: {total}")
    ok = total > 0

    gq = GraphQueries(store)
    deps = gq.direct_imports(cli_path)
    imps = gq.importers(cli_path)
    print(f"{cli_path} imports: {deps}")
    print(f"{cli_path} imported by: {imps}")

    if total < 1:
        print("FAIL: no IMPORTS relationships")
        ok = False
    else:
        print("PASS: Phase 3 IMPORTS present")

    store.close()
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if verify_phase3_imports() else 1)