from pathlib import Path
from core.repository_intelligence.compiler.compiler import RepositoryCompiler


def main():
    repo_name = "Graphify-Labs/graphify"
    local_path = Path("repos") / repo_name.replace("/", "_")

    if not local_path.exists():
        print(f"Repo not found at {local_path}")
        return

    print("=== Phase 1: RepositorySnapshot + Symbols ===")
    compiler = RepositoryCompiler(repo_name=repo_name, local_path=str(local_path))
    snapshot = compiler.compile()

    print(f"Repo:      {snapshot.repo_name}")
    print(f"Files:     {snapshot.total_files}")
    print(f"Languages: {snapshot.languages}")

    py_files = [f for f in snapshot.files if f.language == "python"]
    print(f"Python files: {len(py_files)}")

    total_symbols = sum(len(f.symbols) for f in py_files)
    print(f"Total symbols extracted: {total_symbols}")

    print("\n=== Sample Python files with symbols ===")
    for f in py_files[:12]:
        if not f.symbols:
            continue
        print(f"\n{f.path}")
        for s in f.symbols[:6]:
            print(f"  - {s.kind:8} {s.name:25}  qn={s.qualified_name}")
            print(f"    node_id={s.node_id}")


if __name__ == "__main__":
    main()