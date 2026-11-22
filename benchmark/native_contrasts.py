"""Native gateway development experiment; labels are never loaded during prediction."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace

from benchmark.frozen import seal_predictions
from benchmark.requirement_corpus import load_corpus
from benchmark.requirement_experiment import materialize_case
from core.agent.bundle_agent import BundleAgent, PROMPT_VERSION
from core.input.snapshot import GitSnapshotProvider
from core.intent.service import load_intent
from core.review.artifacts import write_json_atomic
from core.runtime.review_runtime import ReviewRuntime
from core.verification.diff_index import build_diff_index


def predict(corpus: Path, output: Path):
    manifest, cases = load_corpus(corpus)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
    from core.review.worker import review_config
    metadata = {"corpus": manifest, "reviewer_commit": commit, "reviewer_dirty": dirty,
                "provider": review_config(), "prompt_version": PROMPT_VERSION,
                "eligible_for_headline_metrics": False, "transport": "native_gateway_no_llm_callback"}
    write_json_atomic(output/"manifest.json", metadata)
    predictions, reference_inputs = [], []
    for case in cases:
        prompts = []
        class CapturingAgent(BundleAgent):
            def _complete(self, prompt, response_schema=None, *, stage="discovery", max_tokens=1400):
                # Capture input only; do not alter provider, response, schema or budgets.
                if stage in {"semantic_discovery", "assessment_repair"}:
                    prompts.append({"stage": stage, "prompt": prompt,
                                    "schema": response_schema.model_json_schema() if response_schema else None})
                return super()._complete(prompt, response_schema, stage=stage, max_tokens=max_tokens)
        with tempfile.TemporaryDirectory(prefix="ct-contrast-") as directory:
            local = Path(directory)
            base, requirements = materialize_case(local, case)
            provider = GitSnapshotProvider(local)
            intent = load_intent(requirements)
            snapshot = provider.resolve(base, config={"provider": review_config(), "intent_hash": intent.source.content_hash,
                                                      "protocol": PROMPT_VERSION})
            diff = provider.diff(snapshot)
            started = time.monotonic()
            result = ReviewRuntime(agent=CapturingAgent(), rule_engine=lambda *a,**k: []).run(SimpleNamespace(
                review_snapshot=snapshot, input_provider=provider, review_intent=intent, requirement_strategy="link",
                files_changed=sorted(build_diff_index(diff).files), full_diff=diff,
                pr_head_sha=snapshot.head_sha, pr_base_sha=snapshot.base_sha))
            predictions.append({"case_id": case.case_id,"elapsed_seconds": time.monotonic()-started,"result":result.to_dict()})
            reference_inputs.append({"case_id":case.case_id,"discovery_inputs":prompts})
            write_json_atomic(output/"progress.json",predictions)
            print(f"{case.case_id}: {result.decision}, {len(result.product_findings)} finding(s), {result.health.status}",flush=True)
    seal_predictions(output/"predictions.json", predictions)
    seal_predictions(output/"matched-reference-inputs.json", reference_inputs)
    write_json_atomic(output/"seal.json", {"predictions_sha256":hashlib.sha256((output/"predictions.json").read_bytes()).hexdigest(),
        "reference_inputs_sha256":hashlib.sha256((output/"matched-reference-inputs.json").read_bytes()).hexdigest(),
        "manifest_sha256":hashlib.sha256((output/"manifest.json").read_bytes()).hexdigest(),"prediction_count":len(predictions)})


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args=parser.parse_args()
    predict(args.corpus,args.output)
