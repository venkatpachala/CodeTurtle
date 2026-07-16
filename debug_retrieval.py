from core.knowledge_base import KnowledgeBase

# Test collection
kb = KnowledgeBase("FalkorDB_QueryWeaver")

print("Collection:", kb.collection_name)

# Test search
docs = kb.similarity_search("queryweaver", k=5)

print(f"Retrieved {len(docs)} documents")

for i, doc in enumerate(docs):
    print(f"\n--- Document {i+1} ---")
    print("Path:", doc.metadata.get("path"))
    print("Content preview:", doc.page_content[:200])