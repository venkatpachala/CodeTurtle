"""Immutable CodeTurtle benchmark entry point."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, subprocess, sys, time
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
    return {
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); parser.add_argument("--limit", type=int); parser.add_argument("--start", type=int); parser.add_argument("--run-id", default="")
    args = parser.parse_args(); cfg = load_benchmark_config(args.config)
    if args.limit is not None: cfg.limit = args.limit
    if args.start is not None: cfg.start = args.start
    dataset = load_dataset(cfg.dataset_path or os.environ.get("BENCHMARK_DATA_PATH", ""), max_prs=cfg.limit, start=cfg.start)
    run_id = args.run_id or _run_id(cfg.model); run_dir = ROOT / cfg.runs_dir / run_id; pred_dir = run_dir / "predictions"; eval_dir = run_dir / "evaluations"
    pred_dir.mkdir(parents=True, exist_ok=False); eval_dir.mkdir()
    (run_dir / "config.json").write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
    metadata = _git_metadata()
    metadata["dataset_sha256"] = _sha256(dataset.raw_path)
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
        evaluation = evaluate_pr(prediction, [vars(g) for g in pr.golden_comments]); evaluation["pr_url"] = pr.pr_url
        (eval_dir / f"pr_{index + cfg.start:03d}.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
        predictions.append(prediction); evaluations.append(evaluation); manifest.prs_completed += 1
    manifest.completed_at = datetime.now(timezone.utc).isoformat(); (run_dir / "manifest.json").write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
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
