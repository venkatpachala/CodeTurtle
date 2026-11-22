"""Opt-in Docker execution over exported Git objects, never a working checkout.

No host credentials, Docker socket, network, dependency installation or privileged
flags enter the container. Docker availability is required; there is no host fallback.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid

from core.input.snapshot import GitSnapshotProvider, InputError, ReviewSnapshot


@dataclass(frozen=True)
class IsolationProfile:
    image: str
    timeout_seconds: float = 30
    memory_mb: int = 512
    pids: int = 64
    cpus: float = 1
    output_bytes: int = 65536

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64}", self.image):
            raise ValueError("isolated execution requires an immutable image digest")
        if not (0 < self.timeout_seconds <= 600 and 64 <= self.memory_mb <= 2048
                and 8 <= self.pids <= 256 and 0 < self.cpus <= 2 and 1024 <= self.output_bytes <= 1_000_000):
            raise ValueError("isolation profile exceeds supported local limits")


def export_snapshot(provider: GitSnapshotProvider, snapshot: ReviewSnapshot, destination: Path, *, side="head",
                    max_files=10000, max_bytes=50_000_000) -> dict:
    # Enumerate the requested revision, not mutable checkout paths.
    if side not in {"base", "head"}:
        raise ValueError("invalid revision side")
    paths = provider.paths(snapshot, side)
    if len(paths) > max_files:
        raise InputError("isolated export file budget exceeded")
    total = 0
    portable_paths = set()
    for path in paths:
        provider._path(path)
        if any(part.casefold().rstrip(" .") == ".git" for part in path.split("/")):
            raise InputError("Git control path cannot enter isolated source export")
        portable = "/".join(part.casefold().rstrip(" .") for part in path.split("/"))
        reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1,10)), *(f"lpt{i}" for i in range(1,10))}
        if portable in portable_paths or any(part.split(".")[0] in reserved for part in portable.split("/")):
            raise InputError("snapshot paths cannot be exported portably without aliasing")
        portable_paths.add(portable)
        source = provider.read(snapshot, path, side)  # Symlinks/submodules are rejected by the provider.
        total += len(source.content)
        if total > max_bytes:
            raise InputError("isolated export byte budget exceeded")
        output = destination.joinpath(*path.split("/"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(source.content)
    return {"files": len(paths), "bytes": total, "revision_sha": snapshot.revision(side)}


class DockerRunner:
    def __init__(self, profile: IsolationProfile, *, executable="docker", staging_root: Path | None = None):
        self.profile, self.executable, self.staging_root = profile, executable, staging_root

    def _docker(self, *args, timeout=15):
        return subprocess.run([self.executable, *args], capture_output=True, text=True, timeout=timeout,
                              env=os.environ | {"DOCKER_CLI_HINTS": "false"})

    def _mount_path(self, path: Path) -> str:
        if os.name != "nt" and self.executable.lower().endswith(".exe"):
            return subprocess.run(["wslpath", "-w", str(path)], check=True, capture_output=True, text=True, timeout=5).stdout.strip()
        return str(path)

    def run(self, provider: GitSnapshotProvider, snapshot: ReviewSnapshot, command: list[str], *, side="head",
            cancelled=lambda: False) -> dict:
        if not command or any("\0" in arg for arg in command):
            raise ValueError("isolated command must be an argv list")
        name = "ct-review-"+uuid.uuid4().hex
        started = time.monotonic()
        result = {"status": "unavailable", "tests_executed": False, "side": side,
                  "snapshot_id": snapshot.id, "revision_sha": snapshot.revision(side),
                  "profile": asdict(self.profile), "command": command, "output": "", "exit_code": None}
        created, process = False, None
        if self.staging_root:
            self.staging_root.mkdir(parents=True, exist_ok=True)
        try:
            info = self._docker("info", "--format", "{{.OSType}}")
            if info.returncode or info.stdout.strip() != "linux":
                result["reason"] = "linux_docker_engine_unavailable"
                return result
            image = self._docker("image", "inspect", self.profile.image, "--format", "{{.Id}}")
            if image.returncode:
                result["reason"] = "pinned_image_not_installed"
                return result
            result["image_id"] = image.stdout.strip()
            with tempfile.TemporaryDirectory(prefix="ct-source-", dir=self.staging_root) as directory:
                source = Path(directory)/"source"
                source.mkdir()
                result["export"] = export_snapshot(provider, snapshot, source, side=side)
                mount = self._mount_path(source.resolve())
                if "," in mount:
                    raise ValueError("staging path cannot contain mount delimiters")
                options = ["create", "--name", name, "--pull", "never", "--network", "none", "--ipc", "none",
                    "--read-only", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
                    "--pids-limit", str(self.profile.pids), "--memory", f"{self.profile.memory_mb}m",
                    "--memory-swap", f"{self.profile.memory_mb}m", "--cpus", str(self.profile.cpus),
                    "--ulimit", "nofile=128:128", "--ulimit", "core=0:0", "--log-driver", "none",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,mode=1777", "--workdir", "/workspace",
                    "--mount", f"type=bind,source={mount},target=/workspace,readonly",
                    "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
                    "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", self.profile.image, *command]
                creation = self._docker(*options)
                if creation.returncode:
                    result["reason"] = "container_creation_failed"
                    return result
                created = True
                process = subprocess.Popen([self.executable, "start", "--attach", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                captured, exceeded = bytearray(), threading.Event()
                def consume():
                    while chunk := process.stdout.read(4096):
                        remaining = max(0, self.profile.output_bytes-len(captured))
                        captured.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            exceeded.set()
                reader = threading.Thread(target=consume, daemon=True)
                reader.start()
                execution_start = time.monotonic()
                status = ""
                while process.poll() is None:
                    if cancelled():
                        status = "cancelled"
                    elif exceeded.is_set():
                        status = "output_limit"
                    elif time.monotonic()-execution_start > self.profile.timeout_seconds:
                        status = "timed_out"
                    if status:
                        self._docker("kill", name)
                        break
                    time.sleep(0.05)
                process.wait(timeout=10)
                reader.join(timeout=3)
                import json
                inspect = self._docker("inspect", name)
                state = json.loads(inspect.stdout)[0] if inspect.returncode == 0 else {}
                started_at = state.get("State", {}).get("StartedAt", "0001")
                if state.get("State", {}).get("Status") not in {"exited", "dead"} or started_at.startswith("0001"):
                    result.update(status=status or "unavailable", reason="container_start_or_inspection_failed")
                    return result
                exit_code = state.get("State", {}).get("ExitCode", process.returncode)
                result.update(status=status or ("output_limit" if exceeded.is_set() else "passed" if exit_code == 0 else "failed"),
                              tests_executed=True, exit_code=exit_code,
                              output=captured.decode("utf-8", errors="replace"),
                              oom_killed=state.get("State", {}).get("OOMKilled"),
                              controls={key: state.get("HostConfig", {}).get(key) for key in
                                        ("NetworkMode", "ReadonlyRootfs", "CapDrop", "SecurityOpt", "Memory", "MemorySwap", "PidsLimit", "NanoCpus")},
                              user=state.get("Config", {}).get("User"), execution_seconds=time.monotonic()-execution_start)
        except (OSError, ValueError, InputError, subprocess.SubprocessError) as exc:
            result.update(status="unavailable", reason=type(exc).__name__)
        finally:
            if created:
                try:
                    cleanup = self._docker("rm", "--force", name)
                    result["container_removed"] = cleanup.returncode == 0
                except (OSError, subprocess.SubprocessError):
                    result["container_removed"] = False
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            result["elapsed_seconds"] = time.monotonic()-started
        return result
