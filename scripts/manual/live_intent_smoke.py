"""Two synthetic integration cases with actual Ollama calls; not a quality benchmark.

Run in WSL using --windows-ollama when Ollama is bound to Windows localhost.
Prompts are JSON on stdin, never interpolated into shell commands.
Transport overhead is included in timing and is not an inference benchmark.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from core.input.snapshot import GitSnapshotProvider
from core.intent.service import load_intent
from core.review.artifacts import write_json_atomic
from core.runtime.review_runtime import ReviewRuntime

_WINDOWS_REQUEST = (
    "$ErrorActionPreference='Stop'; "
    "$request=[Console]::In.ReadToEnd(); "
    "$response=Invoke-RestMethod -Uri 'http://localhost:11434/api/generate' "
    "-Method Post -ContentType 'application/json; charset=utf-8' -Body $request -TimeoutSec 120; "
    "$response | ConvertTo-Json -Depth 12 -Compress"
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True, timeout=15).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen2.5-coder:3b-instruct")
    parser.add_argument("--windows-ollama", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(".validation/live-intent-smoke.json"))
    args = parser.parse_args()
    calls = []

    def complete(prompt: str) -> str:
        body = json.dumps({"model": args.model, "prompt": prompt, "stream": False,
                           "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1000}})
        started = time.monotonic()
        if args.windows_ollama:
            powershell = shutil.which("powershell.exe")
            if not powershell:
                raise RuntimeError("Windows PowerShell is unavailable from WSL")
            response = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_REQUEST],
                input=body, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=130,
            )
            if response.returncode:
                raise RuntimeError("Windows Ollama request failed")
            data = json.loads(response.stdout.lstrip("\ufeff"))
        else:
            request = urllib.request.Request("http://localhost:11434/api/generate", data=body.encode(),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.load(response)
        calls.append({"model": args.model, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                      "prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": data.get("eval_count"),
                      "latency_seconds": round(time.monotonic() - started, 3)})
        return str(data.get("response") or "")

    before = "def divide(value, denominator):\n    if denominator == 0:\n        return 0\n    return value / denominator\n"
    cases = [
        ("removed-zero-guard", "def divide(value, denominator):\n    return value / denominator\n"),
        ("preserved-zero-guard", before.replace("return value / denominator", "return (value / denominator)")),
    ]
    reports = []
    for name, after in cases:
        with tempfile.TemporaryDirectory(prefix="codeturtle-live-") as directory:
            root = Path(directory)
            git(root, "init")
            git(root, "config", "user.name", "CodeTurtle smoke")
            git(root, "config", "user.email", "smoke@example.invalid")
            (root / "app.py").write_text(before)
            git(root, "add", ".")
            git(root, "commit", "-m", "base")
            base = git(root, "rev-parse", "HEAD")
            (root / "app.py").write_text(after)
            git(root, "add", ".")
            git(root, "commit", "-m", "head")
            requirements_path = root / "requirements.json"
            requirements_path.write_text(json.dumps({"requirements": [{
                "id": "R1", "description": "Zero denominator handling", "paths": ["app.py"],
                "acceptance_criterion": "divide(value, 0) returns zero rather than raising an exception.",
            }]}))
            intent = load_intent(requirements_path)
            provider = GitSnapshotProvider(root)
            snapshot = provider.resolve(base, config={"model": args.model, "intent": intent.source.content_hash})
            first_call = len(calls)
            result = ReviewRuntime(llm=complete, verification_llm=complete).run(SimpleNamespace(
                review_snapshot=snapshot, input_provider=provider, review_intent=intent,
                pr_head_sha=snapshot.head_sha, pr_base_sha=snapshot.base_sha,
                files_changed=["app.py"], full_diff=provider.diff(snapshot),
            ))
            report = result.to_dict()
            report["provenance"]["injected_provider_calls"] = calls[first_call:]
            expectation_met = bool(result.product_findings) if name == "removed-zero-guard" else not result.product_findings
            reports.append({"case_id": name, "result": report, "expected_finding_outcome": expectation_met})
            # Preserve completed case output even if a later model call fails.
            write_json_atomic(args.output, {"scope": "synthetic live integration smoke; not held-out quality",
                "model": args.model, "transport": "windows-powershell-stdin" if args.windows_ollama else "native-http",
                "cases": reports, "calls": calls})
            print(f"{name}: findings={len(result.product_findings)} "
                  f"requirement={result.requirement_assessments[0].status} health={result.health.status}", flush=True)
    print(f"Saved {args.output}; {len(calls)} real model calls", flush=True)
    return 0 if calls and all(case["expected_finding_outcome"] for case in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
