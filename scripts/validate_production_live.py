"""Real Ollama/runtime smoke. Synthetic code inputs; no mocked dependencies.

This is plumbing and diagnostic evidence, never a held-out quality benchmark.
Run: python -m scripts.validate_production_live --output .validation/live.json
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
import time
from pathlib import Path

from core.review.artifacts import write_json_atomic
from core.runtime.review_runtime import ReviewRuntime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=".validation/live.json")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    args = parser.parse_args()
    from config import settings
    settings.ollama_model = args.model
    settings.llm_backend = "ollama"
    settings.execute_tests = False
    cases = {
        "bug": ("def divide(total, count):\n    if count == 0:\n        return 0\n    return total / count\n",
                "def divide(total, count):\n    return total / count\n"),
        "safe": ("def double(value):\n    return value + value\n",
                 "def double(value):\n    return value * 2\n"),
    }
    reports = []
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="live-input-") as temporary:
        root = Path(temporary)
        for name, (before, after) in cases.items():
            old, new = root / "old.py", root / "new.py"
            old.write_bytes(before.encode())
            new.write_bytes(after.encode())
            proc = subprocess.run(["git", "diff", "--no-index", "--", str(old), str(new)], capture_output=True, text=True)
            if proc.returncode != 1:
                raise RuntimeError("real Git diff generation failed")
            lines = proc.stdout.splitlines()
            diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n" + "\n".join(lines[next(i for i, line in enumerate(lines) if line.startswith("@@")):]) + "\n"
            started = time.monotonic()
            result = ReviewRuntime().run(files_changed=["app.py"], full_diff=diff)
            reports.append({"case": name, "elapsed_seconds": time.monotonic() - started,
                            "result": result.to_dict()})
            write_json_atomic(output, {"kind": "synthetic_live_smoke", "model": args.model, "cases": reports})
        settings.ollama_model = "codeturtle-validation-missing-model:does-not-exist"
        result = ReviewRuntime().run(files_changed=["app.py"], full_diff=diff)
        reports.append({"case": "missing_model", "result": result.to_dict()})
        write_json_atomic(output, {"kind": "synthetic_live_smoke", "model": args.model, "cases": reports})
        if result.health.status != "failed" or result.decision is not None:
            raise AssertionError("missing model masqueraded as a valid verdict")
    print(f"Saved real runtime/model diagnostics to {output}")
    return 0 if all(c["result"]["health"]["status"] != "failed" for c in reports[:2]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
