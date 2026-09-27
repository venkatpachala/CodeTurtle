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
from cli.commands.review import PipelineContext


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
            checkout = root / name
            checkout.mkdir()
            def git(*argv):
                return subprocess.run(["git", "-C", str(checkout), *argv], check=True,
                    capture_output=True, text=True).stdout.strip()
            git("init")
            git("config", "user.name", "CodeTurtle validation")
            git("config", "user.email", "validation@example.invalid")
            (checkout / "app.py").write_bytes(before.encode())
            git("add", "app.py")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            (checkout / "app.py").write_bytes(after.encode())
            git("commit", "-am", "head")
            head = git("rev-parse", "HEAD")
            diff = git("diff", base, head) + "\n"
            context = PipelineContext(files_changed=["app.py"], full_diff=diff,
                repo_dir=str(checkout), pr_head_sha=head, pr_base_sha=base)
            started = time.monotonic()
            result = ReviewRuntime().run(context)
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
