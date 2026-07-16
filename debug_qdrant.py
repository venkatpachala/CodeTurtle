from qdrant_client import QdrantClient

client = QdrantClient(path="./qdrant_data")

collection = "FalkorDB_QueryWeaver"

print(client.get_collection(collection))

points, _ = client.scroll(
    collection_name=collection,
    limit=5,
    with_payload=True,
    with_vectors=False,
)

print("\nFirst points:\n")

for p in points:
    print("=" * 60)
    print("ID:", p.id)
    print("Payload:", p.payload)