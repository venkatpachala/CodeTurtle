from core.repository_intelligence import RepositoryIntelligence

def verify_repository_intelligence(repo_name="NousResearch/hermes-agent"):
    """Phase 1 — Repository Intelligence Verification"""

    print("=== Repository Intelligence Verification ===")

    # Initialize
    intelligence = RepositoryIntelligence(
        repo_name=repo_name,
        repo_path=f"repos/{repo_name.replace('/', '_')}"
    )

    # Run verification
    report = intelligence.verify()

    print(f"Files discovered: {report['total_files']}")
    print(f"Python files: {report['python_files']}")
    print(f"Functions extracted: {report['functions']}")
    print(f"Classes extracted: {report['classes']}")
    print(f"Embeddings created: {report['embeddings']}")
    print(f"Qdrant points: {report['qdrant_points']}")

    if report['missing'] == 0:
        print("✅ Repository Intelligence PASSED")
    else:
        print("❌ Repository Intelligence FAILED")

    return report