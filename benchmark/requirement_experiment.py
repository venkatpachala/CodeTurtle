"""Predict input-only development fixtures, seal output, then score separately."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
from typing import Protocol

from benchmark.frozen import seal_predictions
from benchmark.ollama_transport import OllamaExperimentClient
from benchmark.requirement_corpus import RequirementCase, load_corpus
from core.input.snapshot import GitSnapshotProvider
from core.intent.service import load_intent
from core.review.artifacts import write_json_atomic
from core.runtime.review_runtime import ReviewRuntime
from core.verification.diff_index import build_diff_index


class ExperimentProvider(Protocol):
    calls: list[dict]
    def generate(self, stage: str, prompt: str, max_tokens: int = 1400) -> str: ...


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True, timeout=15).stdout.strip()


def materialize_case(root: Path, case: RequirementCase) -> tuple[str, Path]:
    _git(root, "init")
    _git(root, "config", "user.name", "Development fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    for side in ("base", "head"):
        for path, versions in case.files.items():
            target = (root / path).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError("fixture path escaped temporary repository")
            content = getattr(versions, side)
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "--allow-empty", "-m", side)
        if side == "base":
            base = _git(root, "rev-parse", "HEAD")
    requirements_path = root / ".review-requirements.json"
    write_json_atomic(requirements_path, {"requirements": [item.model_dump(mode="json") for item in case.requirements]})
    return base, requirements_path


def run_experiment(corpus: Path, output: Path, provider: ExperimentProvider, *, model: str,
                   strategies: tuple[str, ...] = ("link", "investigate"), limit: int | None = None,
                   selected_cases: tuple[str, ...] = ()) -> dict:
    manifest, cases = load_corpus(corpus)
    if not strategies or len(set(strategies)) != len(strategies) or not set(strategies) <= {"off", "link", "investigate"}:
        raise ValueError("strategies must be unique supported modes")
    if selected_cases:
        known = {case.case_id for case in cases}
        if not set(selected_cases) <= known:
            raise ValueError("unknown selected case")
        cases = [case for case in cases if case.case_id in selected_cases]
    if limit is not None:
        if limit <= 0:
            raise ValueError("case limit must be positive")
        cases = cases[:limit]
    output.mkdir(parents=True, exist_ok=False)
    code_root = Path(__file__).resolve().parents[1]
    metadata = {"scope": manifest["scope"], "eligible_for_headline_metrics": False,
                "corpus": manifest, "model": model, "strategies": list(strategies), "case_count": len(cases),
                "baseline_type": "same-commit link/off ablation, not historical v4",
                "reviewer_commit": _git(code_root, "rev-parse", "HEAD"),
                "reviewer_dirty": bool(_git(code_root, "status", "--porcelain")),
                "budgets": {"model_calls": 12, "prompt_characters": 120000, "between_call_seconds": 300}}
    write_json_atomic(output / "manifest.json", metadata)
    predictions = []
    for index, case in enumerate(cases):
        with tempfile.TemporaryDirectory(prefix="requirement-case-") as directory:
            root = Path(directory)
            base, intent_path = materialize_case(root, case)
            intent = load_intent(intent_path)
            inputs = GitSnapshotProvider(root)
            # Alternate order to expose rather than systematically favor a warm model.
            order = strategies if index % 2 == 0 else tuple(reversed(strategies))
            for strategy in order:
                snapshot = inputs.resolve(base, config={"model": model, "strategy": strategy,
                                                        "intent_sha256": intent.source.content_hash})
                diff = inputs.diff(snapshot)
                first_call = len(provider.calls)
                started = time.monotonic()
                result = ReviewRuntime(
                    llm=lambda prompt: provider.generate("discovery", prompt),
                    verification_llm=lambda prompt: provider.generate("finding_or_link_verifier", prompt, 96),
                    requirement_llm=lambda stage, prompt: provider.generate(f"requirement:{stage}", prompt),
                ).run(SimpleNamespace(
                    review_snapshot=snapshot, input_provider=inputs, review_intent=intent,
                    requirement_strategy=strategy, files_changed=sorted(build_diff_index(diff).files), full_diff=diff,
                    pr_head_sha=snapshot.head_sha, pr_base_sha=snapshot.base_sha,
                ))
                result.provenance.update(model=model, provider="experiment_adapter",
                                         model_calls=list(provider.calls[first_call:]))
                predictions.append({"case_id": case.case_id, "strategy": strategy,
                    "source_case_sha256": hashlib.sha256(json.dumps(case.model_dump(mode="json"), sort_keys=True).encode()).hexdigest(),
                    "elapsed_seconds": round(time.monotonic() - started, 3), "result": result.to_dict()})
                write_json_atomic(output / "progress.json", predictions)
                print(f"{case.case_id} [{strategy}]: health={result.health.status}, "
                      f"findings={len(result.product_findings)}, "
                      f"requirements={[assessment.status for assessment in result.requirement_assessments]}", flush=True)
    path = output / "predictions.json"
    seal_predictions(path, predictions)
    seal = {"predictions_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
            "prediction_count": len(predictions)}
    write_json_atomic(output / "seal.json", seal)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("benchmark/datasets/requirement_development_v1"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--windows-ollama", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--strategies", nargs="+", default=["link", "investigate"], choices=["off", "link", "investigate"])
    args = parser.parse_args()
    run_experiment(args.corpus, args.output, OllamaExperimentClient(args.model, windows=args.windows_ollama),
                   model=args.model, strategies=tuple(args.strategies), limit=args.limit, selected_cases=tuple(args.case))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
