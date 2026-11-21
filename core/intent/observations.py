"""Capture bounded observations from sealed trees before asking a model to reason."""
from __future__ import annotations

import hashlib

from core.domain.observations import SourceObservation, observation_id
from core.input.snapshot import GitSnapshotProvider, InputError, ReviewSnapshot, SourceNotFound


def collect_observations(provider: GitSnapshotProvider, snapshot: ReviewSnapshot,
                         paths: tuple[str, ...], *, max_paths: int = 6,
                         max_chars: int = 18_000, max_lines: int = 120,
                         focus_symbols: dict[str, str] | None = None,
                         focus_lines: dict[str, int] | None = None,
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
            start_line, scope, symbol, dependencies = 1, "file", "", ()
            try:
                source = provider.read(snapshot, path, side)
                # Strict decoding keeps byte identity separate from replacement characters.
                content = source.content.decode("utf-8")
                lines = content.splitlines()
                if focus_symbols and focus_symbols.get(path) and remaining > 0:
                    from core.input.excerpts import capture_excerpt
                    # Do not let historical context consume the entire pair's budget.
                    allowance = max(1, remaining // 2) if side == "base" else remaining
                    excerpt = capture_excerpt(content, path, symbol=focus_symbols[path],
                                              anchor=max(1, (focus_lines or {}).get(path, 1)),
                                              max_lines=max_lines, max_chars=allowance)
                    text, start_line, scope, symbol = excerpt.text, excerpt.start_line, excerpt.scope, excerpt.symbol
                    dependencies = excerpt.unresolved_dependencies
                    complete = excerpt.complete and not dependencies
                else:
                    included = []
                    for line in lines[:max_lines]:
                        proposed = "\n".join([*included, line])
                        if len(proposed) > remaining:
                            break
                        included.append(line)
                    text = "\n".join(included)
                    complete = len(included) == len(lines)
                remaining -= len(text)
                file_hash = source.content_sha256
                status = "success" if complete else "truncated"
                if status == "truncated":
                    detail = "; ".join(dependencies) or "source exceeded shared character or per-file line budget"
                    gaps.append(f"{side}:{path}: {detail}")
                elif scope == "python_function":
                    detail = "Complete lexical function scope; other module source omitted. Runtime monkey-patching and external caller contracts are not established."
            except SourceNotFound:
                status = "absent"
                detail = "path absent from exact committed tree"
            except (InputError, UnicodeDecodeError) as exc:
                status = "error"
                detail = str(exc)
                gaps.append(f"{side}:{path}: unavailable")
            observations.append(SourceObservation(
                id=observation_id(snapshot.id, side, path, text, status, start_line=start_line, scope=scope, symbol=symbol), snapshot_id=snapshot.id,
                revision_sha=snapshot.revision(side), revision_side=side, path=path, status=status,
                text=text, start_line=start_line, end_line=start_line + len(text.splitlines()) - 1, file_sha256=file_hash,
                excerpt_sha256=hashlib.sha256(text.encode()).hexdigest(), detail=detail,
                scope=scope, scope_symbol=symbol, unresolved_dependencies=dependencies,
            ))
    return tuple(observations), tuple(gaps)
