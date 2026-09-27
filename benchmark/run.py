"""Immutable CodeTurtle benchmark entry point."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, subprocess, sys, time
from importlib import metadata as package_metadata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from benchmark.config import load_benchmark_config
from benchmark.dataset import load_dataset
from benchmark.evaluator import evaluate_pr
from benchmark.metrics import aggregate_metrics
from benchmark.gates import evaluate_release_gate
from benchmark.models import RunManifest
from benchmark.reports import render_ascii, render_gate, write_aggregate
from benchmark.splits import load_registered_splits, load_split


def _timeout_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

def _run_id(model: str) -> str:
    return f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{model.replace(':', '-').replace('/', '-')}"


def _git_metadata() -> dict[str, object]:
    def _git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=ROOT, text=True, capture_output=True,
                timeout=10, check=False,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""
    try:
        graphify_version = package_metadata.version("graphifyy")
    except package_metadata.PackageNotFoundError:
        graphify_version = None
    return {
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "reviewer_dirty": bool(_git("status", "--porcelain", "--", "cli", "core", "config")),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "graphify_version": graphify_version,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ollama_metadata(model: str) -> dict[str, object]:
    """Best-effort local model identity without persisting prompts or secrets."""
    details: dict[str, object] = {"ollama_model": model}
    try:
        listed = subprocess.run(["ollama", "list"], text=True, capture_output=True, timeout=10, check=False)
        for row in listed.stdout.splitlines()[1:]:
            fields = row.split()
            if len(fields) >= 2 and fields[0] == model:
                details["ollama_model_id"] = fields[1]
                break
        parameters = subprocess.run(
            ["ollama", "show", model, "--parameters"], text=True, capture_output=True,
            timeout=10, check=False,
        )
        if parameters.returncode == 0:
            details["ollama_parameters"] = parameters.stdout.strip()
        modelfile = subprocess.run(
            ["ollama", "show", model, "--modelfile"], text=True, capture_output=True,
            timeout=10, check=False,
        )
        if modelfile.returncode == 0:
            details["ollama_modelfile_sha256"] = hashlib.sha256(modelfile.stdout.encode("utf-8")).hexdigest()
    except (OSError, subprocess.TimeoutExpired):
        details["ollama_metadata_unavailable"] = True
    return details

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); parser.add_argument("--limit", type=int); parser.add_argument("--start", type=int); parser.add_argument("--run-id", default="")
    parser.add_argument("--split", help="Registered split manifest; prediction selection uses URLs only")
    parser.add_argument("--predict-only", action="store_true", help="Save predictions before exposing gold labels")
    args = parser.parse_args(); cfg = load_benchmark_config(args.config)
    if args.predict_only and not args.split:
        parser.error("--predict-only requires --split to prevent an unlabeled selection")
    if args.limit is not None: cfg.limit = args.limit
    if args.start is not None: cfg.start = args.start
    dataset_path = cfg.dataset_path or os.environ.get("BENCHMARK_DATA_PATH", "")
    split = None
    if args.split:
        split = load_split(args.split)
        registered = load_registered_splits(ROOT / "benchmark" / "datasets")
        if split.path not in {item.path for item in registered}:
            raise ValueError("Only registered, disjoint split manifests may be run")
        if not args.predict_only:
            raise ValueError("Split runs require --predict-only; score only after predictions are sealed")
        # Gold labels are deliberately not loaded during the prediction phase.
        from benchmark.dataset import BenchmarkDataset, BenchmarkPR
        source = Path(dataset_path) if dataset_path else Path("D:/code-review-benchmark/code-review-benchmark/offline/results/benchmark_data.json")
        if not source.is_file():
            raise FileNotFoundError(f"Benchmark dataset not found: {source}")
        selected = split.prs[cfg.start: cfg.start + cfg.limit if cfg.limit is not None else None]
        if not selected:
            raise ValueError("The requested split slice contains no PRs")
        dataset = BenchmarkDataset([BenchmarkPR(pr_url=url) for url in selected], source.resolve())
    else:
        dataset = load_dataset(dataset_path, max_prs=cfg.limit, start=cfg.start)
    run_id = args.run_id or _run_id(cfg.model); run_dir = ROOT / cfg.runs_dir / run_id; pred_dir = run_dir / "predictions"; eval_dir = run_dir / "evaluations"
    pred_dir.mkdir(parents=True, exist_ok=False); eval_dir.mkdir()
    (run_dir / "config.json").write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
    metadata = _git_metadata()
    metadata["dataset_sha256"] = _sha256(dataset.raw_path)
    if cfg.provider == "ollama":
        metadata.update(_ollama_metadata(cfg.model))
    if split:
        metadata.update({
            "split": split.split,
            "split_name": split.name,
            "split_manifest": str(split.path),
            "split_manifest_sha256": _sha256(split.path),
            "used_for_system_design": split.used_for_system_design,
            "eligible_for_headline_metrics": split.eligible_for_headline_metrics,
        })
    manifest = RunManifest(
        run_id=run_id, config=cfg.to_dict(), dataset_path=str(dataset.raw_path),
        prs_total=len(dataset), metadata=metadata,
    )
    predictions = []; evaluations = []
    for index, pr in enumerate(dataset):
        output = pred_dir / f"pr_{index + cfg.start:03d}.json"; env = os.environ.copy(); env["OLLAMA_MODEL"] = cfg.model
        env["LLM_BACKEND"] = cfg.provider
        env["OLLAMA_BASE_URL"] = cfg.base_url
        env["RUNTIME"] = cfg.runtime
        env["BUNDLE_MAX"] = str(cfg.bundle_max)
        env["AGENT_MAX_STEPS"] = str(cfg.agent_max_steps)
        command = ["uv", "run", "python", "-m", "cli.main", "review", pr.repo, str(pr.number), "--dry-run", "--json-output", str(output)]
        if cfg.execution_enabled: command.append("--execute-tests")
        if cfg.execution_install: command.append("--execute-install")
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command, cwd=ROOT, text=True, capture_output=True, env=env,
                timeout=max(1, cfg.review_timeout),
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            output.with_suffix(".log").write_text(
                _timeout_text(exc.stdout) + "\n" + _timeout_text(exc.stderr) + "\nBENCHMARK_TIMEOUT",
                encoding="utf-8",
            )
            manifest.failures.append({"pr_url": pr.pr_url, "error": "timeout", "elapsed_seconds": round(elapsed, 2)})
            continue
        elapsed = time.perf_counter() - started
        output.with_suffix(".log").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
        if completed.returncode:
            manifest.failures.append({"pr_url": pr.pr_url, "return_code": completed.returncode, "elapsed_seconds": round(elapsed, 2)}); continue
        prediction = json.loads(output.read_text(encoding="utf-8")); prediction["run_id"] = run_id; prediction.setdefault("pr_url", pr.pr_url); prediction.setdefault("telemetry", {})["latency_seconds"] = round(elapsed, 2)
        output.write_text(json.dumps(prediction, indent=2), encoding="utf-8")
        predictions.append(prediction); manifest.prs_completed += 1
        if not args.predict_only:
            evaluation = evaluate_pr(prediction, [vars(g) for g in pr.golden_comments]); evaluation["pr_url"] = pr.pr_url
            (eval_dir / f"pr_{index + cfg.start:03d}.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
            evaluations.append(evaluation)
    manifest.completed_at = datetime.now(timezone.utc).isoformat(); (run_dir / "manifest.json").write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    if args.predict_only:
        print(f"Predictions sealed: {manifest.prs_completed}/{manifest.prs_total}; run: {run_dir}")
        return 0 if not manifest.failures else 1
    metrics = aggregate_metrics(evaluations, predictions)
    aggregate = {
        "run_id": run_id,
        "metrics": metrics,
        "release_gate": evaluate_release_gate(metrics, cfg.release_thresholds()),
        "failures": manifest.failures,
    }; write_aggregate(run_dir / "aggregate.json", aggregate)
    print(render_ascii(aggregate["metrics"])); print(render_gate(aggregate["release_gate"])); print(f"Run: {run_dir}")
    return 0 if not manifest.failures else 1
if __name__ == "__main__": raise SystemExit(main())
