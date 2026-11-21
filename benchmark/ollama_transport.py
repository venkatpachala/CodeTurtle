"""Opt-in local experiment transport; Windows bridging never interpolates prompts."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import urllib.request

_WINDOWS_REQUEST = (
    "$ErrorActionPreference='Stop'; $request=[Console]::In.ReadToEnd(); "
    "$response=Invoke-RestMethod -Uri 'http://localhost:11434/api/generate' "
    "-Method Post -ContentType 'application/json; charset=utf-8' -Body $request -TimeoutSec 120; "
    "$response | ConvertTo-Json -Depth 12 -Compress"
)


class OllamaExperimentClient:
    def __init__(self, model: str, *, windows: bool = False):
        self.model = model
        self.windows = windows
        self.calls: list[dict] = []

    def generate(self, stage: str, prompt: str, max_tokens: int = 1400) -> str:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False,
                           "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": max_tokens}})
        call = {"stage": stage, "model": self.model, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "max_output_tokens": max_tokens, "context_tokens": 8192, "temperature": 0, "seed": 42,
                "prompt_tokens": None, "completion_tokens": None, "status": "error"}
        started = time.monotonic()
        try:
            if self.windows:
                executable = shutil.which("powershell.exe")
                if not executable:
                    raise RuntimeError("Windows PowerShell unavailable")
                result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_REQUEST],
                    input=body, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=130)
                if result.returncode:
                    raise RuntimeError("Windows Ollama request failed")
                response = json.loads(result.stdout.lstrip("\ufeff"))
            else:
                request = urllib.request.Request("http://localhost:11434/api/generate", data=body.encode(),
                                                 headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=120) as stream:
                    response = json.load(stream)
            call.update(status="success", prompt_tokens=response.get("prompt_eval_count"),
                        completion_tokens=response.get("eval_count"), done_reason=response.get("done_reason"))
            return str(response.get("response") or "")
        finally:
            call["latency_seconds"] = round(time.monotonic() - started, 3)
            self.calls.append(call)
