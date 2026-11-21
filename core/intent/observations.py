"""Capture bounded observations from sealed trees before asking a model to reason."""
from __future__ import annotations

import hashlib

from core.domain.observations import SourceObservation, observation_id
from core.input.snapshot import GitSnapshotProvider, InputError, ReviewSnapshot, SourceNotFound


def collect_observations(provider: GitSnapshotProvider, snapshot: ReviewSnapshot,
                         paths: tuple[str, ...], *, max_paths: int = 6,
                         max_chars: int = 18_000, max_lines: int = 120,
                         ) -> tuple[tuple[SourceObservation, ...], tuple[str, ...]]:
    if min(max_paths, max_chars, max_lines) <= 0:
        raise ValueError("observation limits must be positive")
    selected = tuple(dict.fromkeys(paths))
    gaps = [f"path budget omitted {path}" for path in selected[max_paths:]]
    observations = []
    remaining = max_chars
    for path in selected[:max_paths]:
        for side in ("base", "head"):
            text, file_hash, detail = "", None, ""
            try:
                source = provider.read(snapshot, path, side)
                # Strict decoding keeps byte identity separate from replacement characters.
                content = source.content.decode("utf-8")
                lines = content.splitlines()
                included = []
                for line in lines[:max_lines]:
                    proposed = "\n".join([*included, line])
                    if len(proposed) > remaining:
                        break
                    included.append(line)
                text = "\n".join(included)
                remaining -= len(text)
                file_hash = source.content_sha256
                status = "success" if len(included) == len(lines) else "truncated"
                if status == "truncated":
                    detail = "source exceeded shared character or per-file line budget"
                    gaps.append(f"{side}:{path}: truncated")
            except SourceNotFound:
                status = "absent"
                detail = "path absent from exact committed tree"
            except (InputError, UnicodeDecodeError) as exc:
                status = "error"
                detail = str(exc)
                gaps.append(f"{side}:{path}: unavailable")
            observations.append(SourceObservation(
                id=observation_id(snapshot.id, side, path, text, status), snapshot_id=snapshot.id,
                revision_sha=snapshot.revision(side), revision_side=side, path=path, status=status,
                text=text, end_line=len(text.splitlines()), file_sha256=file_hash,
                excerpt_sha256=hashlib.sha256(text.encode()).hexdigest(), detail=detail,
            ))
    return tuple(observations), tuple(gaps)
