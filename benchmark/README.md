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

## Frozen-reviewer validation (Phase II)

The reviewed implementation is frozen at git commit `849ca1de93aee4ca01b5c540be121ccf2706344d`.
The prior `signals_v3_dev` result (3 TP, 0 FP, 1 FN on one PR) is **development-only**,
not a headline metric. Its original manifest records model `qwen2.5-coder:7b`,
the full config, dataset SHA-256, timestamp, and the then-dirty source commit
`ad705707`; it does **not** prove that the exact working tree can be reconstructed
from that commit. The stale-`tempfile.size` gold remains unadjudicated.

PR membership is explicit under `benchmark/datasets/{development,validation,test}`.
The loader rejects overlapping PRs. Validation manifests contain URLs only;
gold comments are not loaded during `--predict-only`. Score only after all
predictions are sealed:

```powershell
uv run python -m benchmark.run --config benchmark/configs/coder7b.yaml --split benchmark/datasets/validation/validation_v1.json --predict-only --run-id validation_v1
uv run python -m benchmark.score benchmark/runs/validation_v1 --adjudications benchmark/adjudications/validation_v1.json --failure-adjudications benchmark/adjudications/validation_v1_failures.json
```

Gold status is held in a separate adjudication file: `confirmed`, `ambiguous`,
`rejected`, or `adjudication_required`, with a reason. A PR with unresolved gold
is excluded from confirmed-label metrics; source-label metrics are shown only
as **provisional**. `blocking_recall` is JSON `null` and displayed `N/A` when
there is no blocking gold. Its release check is unmeasured, never pass or fail.

The gold-issue trace uses recorded hypotheses, tool calls, and candidate events.
When a specific gold issue cannot be linked to a candidate, attribution is
`UNATTRIBUTED`, not a guess from another candidate's drop. This is expected
because upstream gold comments generally lack structured file/line identifiers.
Manual issue-specific attribution is stored separately with rationale and
source/trace evidence; it is applied only to confirmed false negatives. A
supplementary run can fill a missing prediction after an infrastructure failure
via `--supplement-run`, but cannot replace an existing prediction or change
the reviewer commit, model, dataset, or split.

The source benchmark contains **no clean PRs**. These validation runs cannot
measure clean-PR false-positive rate; clean controls require separately
adjudicated real PRs. Three PRs are a diagnostic sample, not release evidence.

## Deterministic analysis leads

The V4 reviewer adds bounded `RiskSignal`s before hypothesis discovery. These
are investigation leads, not comments: duplicate Ruby definitions, cross-file
argument contracts, and stale loop-state patterns must still survive proof and
verification. External CLI contracts have source URLs in
`core/analysis/cli_contracts.py`, making dependency knowledge auditable rather
than an undocumented prompt assumption. The current gifsicle link targets a
moving upstream page and is not pinned to a released version.

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
