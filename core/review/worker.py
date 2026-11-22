"""Supervised local review worker: bounded child lifetime and crash recovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from core.review.checkpoints import reviewer_identity
from core.review.jobs import JobStore, LostLease, digest
from core.runtime.models import ReviewResult


def review_config() -> dict:
    from config import settings
    return {"provider": settings.llm_backend,
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini") if settings.llm_backend == "openai" else settings.ollama_model,
            "context_tokens": settings.ollama_context_tokens,
            "rules": settings.rules_enabled, "verification": settings.verification_enabled,
            "endpoint_fingerprint": digest(settings.ollama_base_url) if settings.llm_backend == "ollama" else None}


def terminate_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def _validate(path: Path, payload: dict) -> dict:
    result = ReviewResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
    snapshot = result.provenance.get("input_snapshot") or {}
    if (result.target.base_sha != payload["base_sha"] or result.target.head_sha != payload["head_sha"]
            or snapshot.get("repository_identity") != payload["repo"] or snapshot.get("diff_sha256") != payload["diff_sha256"]):
        raise ValueError("review artifact differs from immutable queued input")
    return result.to_dict()


def work_once(store: JobStore, *, poll_seconds=0.25) -> dict | None:
    job = store.claim()
    if job is None:
        return None
    job_id, token, payload = job["id"], job["token"], job["payload"]
    root = store.path.parent/"artifacts"/job_id
    attempt = root/f"attempt-{job['attempt']}"
    attempt.mkdir(parents=True, exist_ok=True)
    output, log = attempt/"review.json", attempt/"worker.log"
    process = None
    try:
        if payload["reviewer"] != reviewer_identity() or payload["review_config"] != review_config():
            raise ValueError("queued reviewer/configuration differs from worker")
        # Recover an atomically written completed artifact after a crash before DB commit.
        for prior in sorted(root.glob("attempt-*/review.json"), reverse=True):
            try:
                report = _validate(prior, payload)
                if report["health"]["status"] != "failed":
                    return store.finish(job_id, token, artifact=str(prior), report=report)
            except (ValueError, KeyError, OSError):
                continue
        command = [sys.executable, "-m", "cli.main", "review-local", "--repo", payload["repo"],
                   "--base", payload["base_sha"], "--head", payload["head_sha"], "--bundle-max", str(payload["bundle_max"]),
                   "--json-output", str(output), "--checkpoint-dir", str(root/"checkpoints")]
        if payload["static_only"]:
            command.append("--static-only")
        for key, flag in (("requirements", "--requirements"), ("previous", "--previous")):
            if payload.get(key) is not None:
                file = attempt/(key+".json")
                file.write_text(payload[key], encoding="utf-8")
                command.extend([flag, str(file)])
        started, heartbeat = time.monotonic(), time.monotonic()
        with log.open("wb") as stream:
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2], stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt", creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            error = ""
            while process.poll() is None:
                if store.get(job_id)["cancelled"]:
                    error = "cancelled"
                elif time.monotonic()-started > payload["timeout_seconds"]:
                    error = "worker_deadline_exceeded"
                elif log.stat().st_size > 2_000_000:
                    error = "worker_log_limit"
                if error:
                    terminate_tree(process)
                    break
                if time.monotonic()-heartbeat > 5:
                    store.heartbeat(job_id, token)
                    heartbeat = time.monotonic()
                time.sleep(poll_seconds)
        if error or process.returncode:
            return store.finish(job_id, token, artifact=str(output) if output.exists() else "", error=error or "review_process_failed")
        report = _validate(output, payload)
        if payload["reviewer"] != reviewer_identity() or payload["review_config"] != review_config():
            raise ValueError("reviewer/configuration changed during the attempt")
        return store.finish(job_id, token, artifact=str(output), report=report,
                            error="analysis_failed" if report["health"]["status"] == "failed" else "")
    except LostLease:
        if process is not None:
            terminate_tree(process)
        raise
    except Exception as exc:
        if process is not None:
            terminate_tree(process)
        return store.finish(job_id, token, error=type(exc).__name__)
