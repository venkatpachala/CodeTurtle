"""Clone + Graphify index into ~/.codeturtle/repos. No GRAPHIFY_GRAPH_PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from core.repository_knowledge.paths import (
    repo_to_folder,
    resolve_graph_path,
    resolve_repo_dir,
)

RunFn = Callable[..., subprocess.CompletedProcess]
REV_SIDECAR = ".codeturtle-rev"


class WorkspaceError(RuntimeError):
    pass


def graphify_executable() -> str:
    env = (os.environ.get("GRAPHIFY_BIN") or "").strip()
    if env:
        return env
    found = shutil.which("graphify")
    if found:
        return found
    sibling = Path(sys.executable).resolve().parent / (
        "graphify.exe" if os.name == "nt" else "graphify"
    )
    if sibling.is_file():
        return str(sibling)
    return "graphify"


def _run_default(
    argv: Sequence[str],
    *,
    check: bool = True,
    capture_output: bool = False,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv),
        check=check,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def _head_sha(repo_dir: Path, run: RunFn) -> str:
    try:
        proc = run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def _sidecar_path(graph: Path) -> Path:
    return graph.parent / REV_SIDECAR


def graph_is_stale(repo_dir: Path, graph: Path, run: RunFn) -> bool:
    if not graph.is_file():
        return True
    sha = _head_sha(repo_dir, run)
    if not sha:
        return False
    side = _sidecar_path(graph)
    if not side.is_file():
        return True
    return side.read_text(encoding="utf-8").strip() != sha


def clone_url(repo: str, token: str = "") -> str:
    slug = repo.strip().strip("/")
    if token:
        return f"https://x-access-token:{token}@github.com/{slug}.git"
    return f"https://github.com/{slug}.git"


def ensure_clone(
    repo: str,
    *,
    run: Optional[RunFn] = None,
    token: str = "",
) -> Path:
    """Shallow-clone owner/repo into ~/.codeturtle/repos/owner_repo if missing."""
    run = run or _run_default
    dest = resolve_repo_dir(repo)
    if (dest / ".git").exists() or dest.joinpath("graphify-out", "graph.json").is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = clone_url(repo, token=token)
    print(f"[Workspace] clone {repo} → {dest}")
    try:
        run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True,
            timeout=300,
        )
    except subprocess.CalledProcessError as exc:
        err = (getattr(exc, "stderr", None) or getattr(exc, "stdout", None) or str(exc))
        raise WorkspaceError(f"git clone failed for {repo}: {err}") from exc
    except OSError as exc:
        raise WorkspaceError(
            "git is required on PATH to clone repositories."
        ) from exc
    return dest


def fetch_pull_ref(
    repo_dir: Path,
    number: int,
    *,
    run: Optional[RunFn] = None,
) -> None:
    """Best-effort: check out the PR head so Graphify sees new files."""
    if number <= 0:
        return
    run = run or _run_default
    branch = f"codeturtle-pr-{int(number)}"
    try:
        run(
            [
                "git",
                "-C",
                str(repo_dir),
                "fetch",
                "origin",
                f"pull/{int(number)}/head:{branch}",
                "--depth",
                "1",
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        run(
            ["git", "-C", str(repo_dir), "checkout", branch],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except Exception:
        return


def checkout_sha(
    repo_dir: Path,
    sha: str,
    *,
    number: int = 0,
    run: Optional[RunFn] = None,
) -> None:
    """If clone HEAD ≠ pr.head.sha, fetch and check out that commit."""
    run = run or _run_default
    want = (sha or "").strip()
    if not want:
        if number:
            fetch_pull_ref(repo_dir, number, run=run)
        return
    current = _head_sha(repo_dir, run)
    if current == want:
        return
    print(f"[Workspace] checkout sha={want[:12]}")
    try:
        run(
            ["git", "-C", str(repo_dir), "fetch", "origin", want, "--depth", "1"],
            check=True,
            capture_output=True,
            timeout=180,
        )
        run(
            ["git", "-C", str(repo_dir), "checkout", "--force", want],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return
    except Exception:
        pass
    if number:
        fetch_pull_ref(repo_dir, number, run=run)
        current = _head_sha(repo_dir, run)
        if current == want:
            return
        try:
            run(
                ["git", "-C", str(repo_dir), "checkout", "--force", want],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except Exception:
            return


def _graphify_argv(repo_dir: Path) -> List[str]:
    return [
        graphify_executable(),
        "extract",
        str(repo_dir),
        "--code-only",
        "--no-cluster",
    ]


def ensure_index(
    repo: str,
    *,
    run: Optional[RunFn] = None,
    force: bool = False,
) -> Path:
    """Build graphify-out/graph.json with `graphify extract --code-only` if missing/stale."""
    run = run or _run_default
    dest = resolve_repo_dir(repo)
    graph = resolve_graph_path(repo)
    if not force and not graph_is_stale(dest, graph, run):
        print(f"[Workspace] graph ready {graph}")
        return graph
    dest.mkdir(parents=True, exist_ok=True)
    argv = _graphify_argv(dest)
    print(f"[Workspace] graphify {' '.join(argv[1:])}")
    try:
        run(argv, check=True, capture_output=False, timeout=1800, cwd=str(dest))
    except FileNotFoundError as exc:
        raise WorkspaceError(
            "Graphify is not on PATH. Reinstall with: "
            'uv tool install "git+https://github.com/venkatpachala/CodeTurtle.git@v0.3.0"'
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise WorkspaceError(f"graphify failed for {repo}: {exc}") from exc
    if not graph.is_file():
        raise WorkspaceError(
            f"graphify finished but {graph} is missing. "
            "Expected graphify-out/graph.json under the clone."
        )
    sha = _head_sha(dest, run)
    if sha:
        graph.parent.mkdir(parents=True, exist_ok=True)
        _sidecar_path(graph).write_text(sha + "\n", encoding="utf-8")
    return graph


def ensure_workspace(
    repo: str,
    number: int = 0,
    *,
    run: Optional[RunFn] = None,
    token: str = "",
    force_index: bool = False,
    head_sha: str = "",
) -> Path:
    """Clone (if needed) + checkout PR SHA + Graphify if graph missing or SHA changed."""
    run = run or _run_default
    dest = ensure_clone(repo, run=run, token=token)
    checkout_sha(dest, head_sha, number=number, run=run)
    return ensure_index(repo, run=run, force=force_index)
