# CodeTurtle Benchmark Integration

Tools to evaluate CodeTurtle on the official **Code Review Benchmark** (50 PRs).

## Directory Structure

```text
D:\CodeTurtle\
└── benchmark\
    ├── runner.py        # Subprocess runner for batch benchmark PRs
    ├── models.py        # BenchmarkFinding and BenchmarkReview data classes
    ├── integrate.py     # Integrates results into benchmark_data.json
    ├── adapter.py       # Review state adapter functions
    ├── results\         # Per-PR JSON outputs, logs, and failures.json
    └── README.md
```

## Reproducible benchmark workflow

The current benchmark path is `benchmark.run`. It stores the exact config,
dataset SHA-256, git revision/dirty flag, per-PR predictions, evaluations,
latency, agent-stage diagnostics, aggregate metrics, and a release gate.

```powershell
uv run python -m benchmark.run --config benchmark/configs/coder7b.yaml --limit 10
```

If matching or metric code changes, recompute a saved run without paying for
the model again:

```powershell
uv run python -m benchmark.recompute benchmark/runs/<run-id>
```

Do not claim a release from a smoke run. The default gate requires at least 10
PRs plus precision, blocking recall, false-positive, reliability, latency, and
decision-quality thresholds.

## Deterministic analysis leads

The V4 reviewer adds bounded `RiskSignal`s before hypothesis discovery. These
are investigation leads, not comments: duplicate Ruby definitions, cross-file
argument contracts, and stale loop-state patterns must still survive proof and
verification. External CLI contracts are versioned with source URLs in
`core/analysis/cli_contracts.py`, making dependency knowledge auditable rather
than an undocumented prompt assumption.

## Legacy integration workflow

### 1. Run Benchmark Runner on PRs

```powershell
$env:OLLAMA_MODEL="qwen2.5:7b"

# Run a test batch of 3 PRs
python benchmark\runner.py --limit 3 --model qwen2.5:7b

# Run all 50 benchmark PRs (skips completed PRs)
python benchmark\runner.py --model qwen2.5:7b
```

### 2. Verify Generated JSON Results

```powershell
python -c "import json,glob; [(json.load(open(f)), print('OK',f)) for f in glob.glob('benchmark/results/*.json') if not f.endswith('failures.json')]"
```

### 3. Integrate Reviews into `benchmark_data.json`

```powershell
python benchmark\integrate.py
```

### 4. Run Official Benchmark Extraction & Judging

```powershell
cd D:\code-review-benchmark\code-review-benchmark\offline

# Step 2: Extract candidate issues from reviews
uv run python -m code_review_benchmark.step2_extract_comments --tool codeturtle

# Step 2.5: Deduplicate review candidates
uv run python -m code_review_benchmark.step2_5_dedup_candidates --tool codeturtle

# Step 3: LLM judge against human golden comments
uv run python -m code_review_benchmark.step3_judge_comments --tool codeturtle

# Launch leaderboard dashboard
uv run python analysis/benchmark_dashboard.py
```
