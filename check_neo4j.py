from dotenv import load_dotenv
load_dotenv()

from core.repository_intelligence.graph.store import GraphStore

store = GraphStore()
print("URI:", store.uri)
print("User:", store.user)

driver = store.connect()
with driver.session() as s:
    s.run("MERGE (m:DebugMarker {id: 'codeturtle'}) SET m.ts = timestamp()")
    print("nodes:", s.run("MATCH (n) RETURN count(n) AS c").single()["c"])
    print("marker:", s.run("MATCH (m:DebugMarker) RETURN m.id AS id").data())
store.close()