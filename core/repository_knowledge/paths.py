from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import settings


def repo_to_folder(repo: str) -> str:
    """FalkorDB/QueryWeaver -> FalkorDB_QueryWeaver"""
    return repo.strip().replace("\\", "/").replace("/", "_")


def resolve_repo_dir(repo: str, repos_root: Optional[str] = None) -> Path:
    root = Path(repos_root or getattr(settings, "repos_root", "repos"))
    return root / repo_to_folder(repo)


def resolve_graph_path(repo: str, repos_root: Optional[str] = None) -> Path:
    """
    Universal graph location:

        repos/<owner_repo>/graphify-out/graph.json
    """
    repo_dir = resolve_repo_dir(repo, repos_root)
    # Prefer settings override pattern if present, else standard Graphify layout
    rel = getattr(settings, "graphify_graph_filename", "graphify-out/graph.json")
    return (repo_dir / rel).resolve()


def ensure_graph_exists(repo: str) -> Path:
    path = resolve_graph_path(repo)
    if not path.exists():
        repo_dir = resolve_repo_dir(repo)
        raise FileNotFoundError(
            f"Graphify graph not found for '{repo}'.\n"
            f"Expected: {path}\n\n"
            f"Build it with:\n"
            f"  cd {repo_dir}\n"
            f"  graphify . --code-only\n"
        )
    return path