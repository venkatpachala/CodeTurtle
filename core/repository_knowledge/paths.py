from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def repo_to_folder(repo: str) -> str:
    """FalkorDB/QueryWeaver -> FalkorDB_QueryWeaver"""
    return repo.strip().replace("\\", "/").replace("/", "_")


def _default_repos_root() -> Path:
    from core.user_config import repos_dir

    return repos_dir()


def resolve_repo_dir(repo: str, repos_root: Optional[str] = None) -> Path:
    folder = repo_to_folder(repo)
    if repos_root:
        return Path(str(repos_root)).expanduser() / folder
    env_root = (os.environ.get("CODETURTLE_REPOS_ROOT") or "").strip()
    if env_root:
        return Path(env_root).expanduser() / folder
    home_dir = _default_repos_root() / folder
    cwd_legacy = Path("repos") / folder
    if home_dir.exists():
        return home_dir
    if cwd_legacy.exists():
        return cwd_legacy
    return home_dir


def resolve_graph_path(repo: str, repos_root: Optional[str] = None) -> Path:
    """
    Universal graph location:

        ~/.codeturtle/repos/<owner_repo>/graphify-out/graph.json
    """
    repo_dir = resolve_repo_dir(repo, repos_root)
    rel = "graphify-out/graph.json"
    try:
        from config import settings

        rel = getattr(settings, "graphify_graph_filename", rel) or rel
    except Exception:
        pass
    return (repo_dir / rel).resolve()


def ensure_graph_exists(repo: str) -> Path:
    path = resolve_graph_path(repo)
    if not path.exists():
        repo_dir = resolve_repo_dir(repo)
        raise FileNotFoundError(
            f"Graphify graph not found for '{repo}'.\n"
            f"Expected: {path}\n\n"
            f"CodeTurtle builds this automatically on review. Or:\n"
            f"  cd {repo_dir}\n"
            f"  graphify extract . --code-only\n"
        )
    return path
