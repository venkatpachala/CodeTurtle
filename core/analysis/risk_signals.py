"""Small static analyses that seed review hypotheses with concrete evidence.

These are deliberately bounded heuristics, not a replacement for a compiler or
the verifier.  They surface deterministic facts that a review model should not
have to rediscover from a truncated diff.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from core.pr_facts import normalize_path
from core.analysis.cli_contracts import GIFSICLE_RESIZE_FIT, violates_gifsicle_resize_fit
from core.runtime.models import Bundle, Candidate
from core.verification.diff_index import DiffIndex

_RUBY_DEF_RE = re.compile(r"^\s*def\s+(self\.)?([A-Za-z_]\w*[!?=]?)\s*(\([^)]*\))?")
_PERCENT_CALL_RE = re.compile(
    r"(?P<receiver>[A-Z]\w*(?:::[A-Z]\w*)*)\.(?P<method>[a-z_]\w*[!?=]?)\((?P<args>[^\n]*?['\"]\d+(?:\.\d+)?%['\"][^\n]*)\)"
)
_WHILE_SIZE_RE = re.compile(r"while\s+[^\n]*\b(?P<var>[A-Za-z_]\w*)\.size\s*>")


@dataclass(frozen=True)
class RiskSignal:
    kind: str
    file: str
    symbol: str = ""
    lines: tuple[int, ...] = ()
    evidence: tuple[str, ...] = ()
    description: str = ""
    confidence: float = 0.0
    required_evidence: tuple[str, ...] = ("source",)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["lines"] = list(self.lines)
        data["evidence"] = list(self.evidence)
        data["required_evidence"] = list(self.required_evidence)
        return data


def _read(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > 1_000_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _repo_file(root: Path, relative: str) -> Path | None:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _hunk_lines(index: DiffIndex, path: str) -> list[int]:
    out: list[int] = []
    for hunk in index.hunks_for(path):
        start = int(hunk.new_start or 0)
        if start:
            out.append(start)
    return out


def _changed_text(index: DiffIndex, path: str) -> str:
    return "\n".join(str(h.added or "") for h in index.hunks_for(path))


def _duplicate_definition_signals(root: Path, paths: Iterable[str], index: DiffIndex) -> list[RiskSignal]:
    signals: list[RiskSignal] = []
    for relative in paths:
        if not relative.lower().endswith(".rb"):
            continue
        source = _read(_repo_file(root, relative) or Path())
        definitions: dict[str, list[tuple[int, str]]] = {}
        for line_no, line in enumerate(source.splitlines(), start=1):
            match = _RUBY_DEF_RE.match(line)
            if not match:
                continue
            symbol = f"self.{match.group(2)}" if match.group(1) else match.group(2)
            definitions.setdefault(symbol, []).append((line_no, line.strip()))
        changed_starts = _hunk_lines(index, relative)
        for symbol, defs in definitions.items():
            if len(defs) < 2:
                continue
            # Only report a repository fact when the changed hunk touches the
            # duplicate region; an old duplicate elsewhere is not PR evidence.
            if changed_starts and not any(abs(line - start) <= 20 for line, _ in defs for start in changed_starts):
                continue
            lines = tuple(line for line, _ in defs)
            evidence = tuple(f"{relative}:{line}: {text}" for line, text in defs[:3])
            signals.append(RiskSignal(
                kind="duplicate_definition",
                file=relative,
                symbol=symbol,
                lines=lines,
                evidence=evidence,
                description=(
                    f"{symbol} is defined {len(defs)} times in the same Ruby file; "
                    "later definitions override earlier definitions and may change its arity."
                ),
                confidence=0.98,
                required_evidence=("source", "callers", "tests"),
            ))
    return signals


def _find_ruby_class_file(root: Path, receiver: str) -> Path | None:
    stem = re.sub(r"(?<!^)(?=[A-Z])", "_", receiver.split("::")[-1]).lower()
    target = f"{stem}.rb"
    for path in root.rglob(target):
        if any(part in {".git", "vendor", "node_modules", "tmp"} for part in path.parts):
            continue
        return path
    return None


def _contract_signals(root: Path, paths: Iterable[str], index: DiffIndex) -> list[RiskSignal]:
    signals: list[RiskSignal] = []
    for relative in paths:
        added = _changed_text(index, relative)
        for match in _PERCENT_CALL_RE.finditer(added):
            receiver, method, args = match.group("receiver"), match.group("method"), match.group("args")
            target = _find_ruby_class_file(root, receiver)
            target_text = _read(target or Path())
            if not target_text:
                continue
            # The finding is not "percentages are always bad". It is a specific
            # animated execution path whose downstream CLI accepts geometry.
            if not ("allow_animation" in args and "gifsicle" in target_text and "--resize-fit" in target_text):
                continue
            argument_match = re.search(r"\d+(?:\.\d+)?%", args)
            if argument_match is None or not violates_gifsicle_resize_fit(argument_match.group(0)):
                continue
            try:
                target_rel = target.relative_to(root).as_posix() if target else ""
            except ValueError:
                target_rel = ""
            evidence = (
                f"{relative}: changed call {receiver}.{method}(..., {re.search(r'\d+(?:\.\d+)?%', args).group(0)}, allow_animation: ...)",
                f"{target_rel}: animated path invokes gifsicle --resize-fit with dimensions",
                f"known_cli_contract: gifsicle --resize-fit {GIFSICLE_RESIZE_FIT.description} ({GIFSICLE_RESIZE_FIT.source_url})",
            )
            signals.append(RiskSignal(
                kind="cross_file_argument_contract",
                file=relative,
                symbol=f"{receiver}.{method}",
                lines=tuple(_hunk_lines(index, relative)),
                evidence=evidence,
                description=(
                    "A percentage dimensions argument reaches an animated GIF path that passes "
                    "dimensions to gifsicle --resize-fit, whose documented contract requires WxH geometry. "
                    "Animated downsizing will fail for this input."
                ),
                confidence=0.98,
                required_evidence=("source", "callees", "tests"),
            ))
    return signals


def _stale_loop_signals(paths: Iterable[str], index: DiffIndex) -> list[RiskSignal]:
    signals: list[RiskSignal] = []
    for relative in paths:
        added = _changed_text(index, relative)
        for match in _WHILE_SIZE_RE.finditer(added):
            variable = match.group("var")
            tail = added[match.end(): match.end() + 900]
            # Same path used as input/output strongly suggests an in-place file
            # mutation. A loop condition reading a cached wrapper size then needs
            # an explicit refresh or a new wrapper.
            in_place = re.search(rf"\b{re.escape(variable)}\.path\s*,\s*{re.escape(variable)}\.path\b", tail)
            refresh = re.search(rf"\b{re.escape(variable)}\s*=|\b{re.escape(variable)}\.re(?:open|wind|load|fresh)", tail)
            if not in_place or refresh:
                continue
            signals.append(RiskSignal(
                kind="stale_loop_state",
                file=relative,
                symbol="",
                lines=tuple(_hunk_lines(index, relative)),
                evidence=(
                    f"loop condition reads {variable}.size",
                    f"loop body mutates {variable}.path in place ({in_place.group(0)})",
                    f"no {variable} refresh or reassignment appears in the changed loop body",
                ),
                description=(
                    "The loop condition may observe stale file metadata after an in-place mutation. "
                    "Verify whether size is refreshed after each transformation and whether the loop terminates."
                ),
                confidence=0.76,
                required_evidence=("source", "callees", "tests"),
            ))
    return signals


def analyze_risk_signals(
    *,
    repo_dir: str | Path | None,
    files_changed: Sequence[str],
    index: DiffIndex,
) -> list[RiskSignal]:
    """Return bounded, deterministic PR risk signals from changed source files."""
    if not repo_dir:
        return []
    root = Path(repo_dir)
    if not root.is_dir():
        return []
    paths = list(dict.fromkeys(normalize_path(path) for path in files_changed if path))[:100]
    signals = (
        _duplicate_definition_signals(root, paths, index)
        + _contract_signals(root, paths, index)
        + _stale_loop_signals(paths, index)
    )
    # Prevent duplicate signals from noisy multi-hunk files.
    unique: dict[tuple[str, str, str], RiskSignal] = {}
    for signal in signals:
        unique[(signal.kind, signal.file, signal.symbol)] = signal
    return list(unique.values())[:24]


def attach_signals_to_bundles(bundles: Sequence[Bundle], signals: Sequence[RiskSignal]) -> None:
    for bundle in bundles:
        paths = {normalize_path(path) for path in bundle.paths}
        bundle.risk_signals = [signal.to_dict() for signal in signals if normalize_path(signal.file) in paths]


def attach_signals_to_candidates(
    candidates: Sequence[Candidate], signals: Sequence[RiskSignal], index: DiffIndex,
) -> None:
    """Preserve static evidence through proof and verification stages."""
    for candidate in candidates:
        matched = [
            signal for signal in signals
            if normalize_path(signal.file) == normalize_path(candidate.file)
            and (not signal.symbol or signal.symbol == candidate.symbol)
        ]
        if not matched:
            continue
        candidate.risk_signals = [signal.to_dict() for signal in matched]
        for signal in matched:
            if signal.kind != "duplicate_definition":
                continue
            for item in signal.evidence:
                match = re.match(r"^.+?:(\d+):\s*(.*)$", str(item))
                if match is None:
                    continue
                try:
                    line = int(match.group(1))
                except ValueError:
                    continue
                code = match.group(2)
                added = "\n".join(str(hunk.added or "") for hunk in index.hunks_for(candidate.file))
                if " ".join(code.split()) in " ".join(added.split()):
                    candidate.existing_code = code
                    candidate.start_line = line
                    break
