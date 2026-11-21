"""Prepare pinned PR comparison objects without changing the working tree."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Callable

from core.input.snapshot import GitSnapshotProvider, InputError, ReviewSnapshot


def prepare_pr_snapshot(
    root: str | Path, base_sha: str, head_sha: str, review_diff: str, *,
    timeout_seconds: float = 90, depths: tuple[int, ...] = (32, 128, 512),
    run: Callable | None = None,
) -> tuple[GitSnapshotProvider, ReviewSnapshot, dict]:
    """Try local objects first, then at most three finite-depth fetches.

    No branch name is trusted and no checkout/reset/unshallow is performed.
    Source BASE is the merge base; the target tip remains separately identified.
    Unavailable history is an input limitation, never an empty/clean comparison.
    """
    if not all(re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", sha) for sha in (base_sha, head_sha)):
        raise InputError("PR preparation requires complete commit hashes")
    if timeout_seconds <= 0 or not depths or any(depth < 1 or depth > 2048 for depth in depths) or len(depths) > 3:
        raise ValueError("invalid PR history preparation limits")
    from core.workspace import _run_default
    run = run or _run_default
    deadline = time.monotonic() + timeout_seconds
    provider = GitSnapshotProvider(root, timeout_seconds=min(15, timeout_seconds))
    config = {"review_diff_sha256": hashlib.sha256(review_diff.encode()).hexdigest(),
              "preparation_version": "pinned-history-v1"}
    attempted: list[int] = []
    for depth in (None, *depths):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if depth is not None:
            attempted.append(depth)
            try:
                run(["git", "-C", str(root), "fetch", "--no-tags", "--no-recurse-submodules",
                     "--depth", str(depth), "origin", base_sha, head_sha],
                    check=True, capture_output=True, timeout=remaining)
            except Exception:
                # Do not leak remote authentication output or invent a BASE.
                continue
        if deadline <= time.monotonic():
            break
        # resolve performs at most four Git commands; reserve their total time.
        provider.timeout_seconds = min(15, (deadline - time.monotonic()) / 5)
        try:
            snapshot = provider.resolve(base_sha, head_sha, comparison="merge_base", config=config)
        except InputError:
            continue
        return provider, snapshot, {
            "status": "ready", "attempted_fetch_depths": attempted,
            "snapshot_id": snapshot.id, "review_diff_sha256": config["review_diff_sha256"],
            "comparison_base_sha": snapshot.revision("base"),
        }
    raise InputError("pinned PR comparison unavailable within bounded history preparation")
