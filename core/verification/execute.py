"""Phase 4.3 / 4.3b — optional isolated pytest, with opt-in worktree install.

Default off. Never pytest the dirty repos/ tree as a silent fallback.
Lockfile-only PRs skip. Path jail + timeout. No shell=True.
4.3b: --execute-install may uv sync / venv from a recognized manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import settings
from core.pr_facts import is_lockfile, is_source_file, normalize_path
from core.repository_knowledge.paths import resolve_repo_dir, repo_to_folder
from core.verification.models import ExecutionRecord, ExecutionSlice
from core.verification.policy import (
    adjust_testing_nit,
    looks_like_testing_nit,
    recommendation_from_verification,
)


_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_FAILED_NAME_RE = re.compile(r"^FAILED\s+(\S+)", re.M)
_PYPROJECT_NAME_RE = re.compile(r'(?m)^name\s*=\s*["\']([A-Za-z0-9._-]+)["\']')

Runner = Callable[..., Any]


def _env_enabled(state: dict) -> bool:
    if state.get("execute_tests"):
        return True
    if getattr(settings, "execute_tests", False) is True:
        return True
    v = (os.environ.get("CODETURTLE_EXECUTE_TESTS") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _install_enabled(state: dict) -> bool:
    """Install is a no-op unless execute-tests is also on."""
    if not _env_enabled(state):
        return False
    if state.get("execute_install") is True:
        return True
    if getattr(settings, "execute_install", False) is True:
        return True
    v = (os.environ.get("CODETURTLE_EXECUTE_INSTALL") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _install_requested(state: dict) -> bool:
    if state.get("execute_install") is True:
        return True
    if getattr(settings, "execute_install", False) is True:
        return True
    v = (os.environ.get("CODETURTLE_EXECUTE_INSTALL") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def execution_skip_reason(state: dict) -> Optional[str]:
    """Pure skip gate. No subprocess."""
    if not _env_enabled(state):
        return "disabled"
    facts = state.get("pr_facts") or {}
    if str(facts.get("classification") or "") == "lockfile-only":
        return "lockfile-only"
    files = list(facts.get("files_changed") or state.get("files_changed") or [])
    if not any(is_source_file(f) for f in files):
        return "no_source_files"
    return None


def is_pytest_file(path: str) -> bool:
    p = normalize_path(path)
    base = p.split("/")[-1].lower()
    if not base.endswith(".py"):
        return False
    return base.startswith("test_") or base.endswith("_test.py")


def collect_test_paths(
    findings: List[dict],
    files_changed: List[str],
    max_files: int = 8,
) -> List[str]:
    """related_tests first, then changed test_*.py. Cap. No full-suite pytest."""
    related: List[str] = []
    for f in findings or []:
        for p in f.get("related_tests") or []:
            if is_pytest_file(str(p)) and not is_lockfile(str(p)):
                related.append(normalize_path(str(p)))
    changed_tests = [
        normalize_path(p)
        for p in (files_changed or [])
        if is_pytest_file(p) and not is_lockfile(p)
    ]
    ordered = list(dict.fromkeys(related + changed_tests))
    if len(ordered) <= max_files:
        return ordered
    stems = set()
    for f in findings or []:
        src = normalize_path(str(f.get("file") or ""))
        if src:
            stems.add(src.split("/")[-1].rsplit(".", 1)[0].lower())
    preferred, rest = [], []
    for p in ordered:
        base = p.split("/")[-1].lower()
        if any(s and s in base for s in stems):
            preferred.append(p)
        else:
            rest.append(p)
    return (preferred + rest)[:max_files]


def jail_relpath(worktree: Path, rel: str) -> Optional[str]:
    """Return a relative posix path if it exists under worktree. Reject .. and abs."""
    if not rel or not str(rel).strip():
        return None
    raw = str(rel).replace("\\", "/").strip()
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return None
    parts = Path(raw).parts
    if ".." in parts:
        return None
    root = worktree.resolve()
    candidate = (worktree / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate.relative_to(root).as_posix()


def detect_pytest(root: Path) -> bool:
    """Python pytest only. JS is 4.3c."""
    if (root / "pytest.ini").is_file() or (root / "conftest.py").is_file():
        return True
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if "[tool.pytest" in text:
            return True
    tests_dir = (root / "tests").is_dir() or (root / "api" / "tests").is_dir()
    return bool(tests_dir and shutil.which("pytest"))


def resolve_pytest_bin(
    worktree: Path,
    repo_dir: Optional[Path] = None,
    which: Callable = shutil.which,
) -> Optional[str]:
    """Prefer worktree/.venv, then clone/.venv, then PATH."""
    names = (
        (".codeturtle-venv", "Scripts", "pytest.exe"),
        (".codeturtle-venv", "Scripts", "pytest"),
        (".codeturtle-venv", "bin", "pytest"),
        (".venv", "Scripts", "pytest.exe"),
        (".venv", "Scripts", "pytest"),
        (".venv", "bin", "pytest"),
    )
    roots = [worktree]
    if repo_dir is not None:
        roots.append(repo_dir)
    for root in roots:
        if root is None:
            continue
        for parts in names:
            cand = root.joinpath(*parts)
            if cand.is_file():
                return str(cand)
    found = which("pytest")
    return str(found) if found else None


def parse_pytest_output(text: str, exit_code: Optional[int]) -> Dict[str, Any]:
    blob = text or ""
    passed = None
    failed = None
    m = _PASSED_RE.search(blob)
    if m:
        passed = int(m.group(1))
    m = _FAILED_RE.search(blob)
    if m:
        failed = int(m.group(1))
    names = _FAILED_NAME_RE.findall(blob)
    if passed is None and failed is None and exit_code == 0:
        passed = 0
        failed = 0
    if passed is not None and failed is None:
        failed = 0
    if failed is not None and passed is None and exit_code != 0:
        passed = 0
    return {"passed": passed, "failed": failed, "failed_names": names}


def checkout_pr_head(
    repo_dir: Path,
    sha: str,
    dest: Path,
    *,
    runner: Runner = subprocess.run,
) -> tuple[bool, str]:
    """Fetch SHA and git worktree add --detach. Never use a dirty repos/ tree."""
    if not sha or not repo_dir.is_dir():
        return False, "checkout_failed"
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        runner(
            ["git", "-C", str(repo_dir), "worktree", "remove", "--force", str(dest)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        shutil.rmtree(dest, ignore_errors=True)
    fetch = runner(
        ["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin", sha],
        capture_output=True,
        text=True,
        timeout=120,
    )
    add = runner(
        ["git", "-C", str(repo_dir), "worktree", "add", "--detach", str(dest), sha],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if getattr(add, "returncode", 1) != 0:
        add = runner(
            ["git", "-C", str(repo_dir), "worktree", "add", "--detach", str(dest), sha],
            capture_output=True,
            text=True,
            timeout=60,
        )
    if getattr(add, "returncode", 1) != 0 or not dest.is_dir():
        return False, "checkout_failed"
    _ = fetch
    return True, ""


def _run_cmd(
    cmd: List[str],
    cwd: Path,
    timeout_s: int,
    runner: Runner,
    extra_env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    kwargs: Dict[str, Any] = {
        "cwd": str(cwd),
        "capture_output": True,
        "text": True,
        "timeout": timeout_s,
    }
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
        kwargs["env"] = env
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return runner(cmd, **kwargs)


def _venv_python(root: Path) -> Optional[str]:
    for parts in (
        ("Scripts", "python.exe"),
        ("Scripts", "python"),
        ("bin", "python"),
        ("bin", "python3"),
    ):
        cand = root.joinpath(*parts)
        if cand.is_file():
            return str(cand)
    return None


def _venv_pytest(root: Path) -> Optional[str]:
    for parts in (
        ("Scripts", "pytest.exe"),
        ("Scripts", "pytest"),
        ("bin", "pytest"),
    ):
        cand = root.joinpath(*parts)
        if cand.is_file():
            return str(cand)
    return None


def _project_package_name(worktree: Path) -> Optional[str]:
    p = worktree / "pyproject.toml"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m = _PYPROJECT_NAME_RE.search(text)
    if not m:
        return None
    return m.group(1).replace("-", "_")


def _probe_import(
    python: str,
    modules: List[str],
    runner: Runner,
    cwd: Path,
) -> bool:
    if not python or not modules:
        return False
    code = "; ".join(f"import {m}" for m in modules)
    try:
        proc = _run_cmd([python, "-c", code], cwd, 15, runner)
    except Exception:
        return False
    return int(getattr(proc, "returncode", 1) or 0) == 0


def detect_python_manifest(
    worktree: Path, which: Callable = shutil.which
) -> Tuple[Optional[str], Optional[str]]:
    """Return (kind, skip_reason). First recognized manifest wins."""
    if (worktree / "uv.lock").is_file():
        return "uv_lock", None
    if (worktree / "pyproject.toml").is_file() and which("uv"):
        return "uv_pyproject", None
    if (worktree / "poetry.lock").is_file():
        return "poetry", "unsupported_installer=poetry"
    if (worktree / "requirements.txt").is_file():
        return "requirements", None
    return None, "deps_missing"


def _lock_hash(worktree: Path) -> str:
    for name in ("uv.lock", "poetry.lock", "requirements.txt"):
        p = worktree / name
        if p.is_file():
            try:
                data = p.read_bytes()
            except OSError:
                data = b""
            return hashlib.sha256(data).hexdigest()[:16]
    py = worktree / "pyproject.toml"
    if py.is_file():
        try:
            data = py.read_bytes()
        except OSError:
            data = b""
        return hashlib.sha256(data).hexdigest()[:16]
    return "nolock"


def _venv_cache_dir(repo: str, worktree: Path) -> Path:
    folder = repo_to_folder(repo or "unknown")
    digest = _lock_hash(worktree)
    dest = Path("tmp") / "codeturtle-exec-venv" / f"{folder}_{digest}"
    dest.mkdir(parents=True, exist_ok=True)
    return dest.resolve()


def _uv_env(cache: Path) -> Dict[str, str]:
    return {"UV_PROJECT_ENVIRONMENT": str(cache)}


def prepare_python_env(
    worktree: Path,
    repo_dir: Path,
    state: dict,
    *,
    runner: Runner,
    which: Callable,
) -> Dict[str, Any]:
    """Resolve a pytest-capable env. May uv sync / venv when install is on.

    --execute-install implies network for this run (lock/manifest only).
    Never pip-installs pytest globally or packages named in the PR body.
    """
    install_on = _install_enabled(state)
    install_timeout = int(
        state.get("execute_install_timeout_s")
        or getattr(settings, "execute_install_timeout_s", 180)
    )
    repo = str(state.get("repo") or "")

    wt_ct = _venv_python(worktree / ".codeturtle-venv")
    if wt_ct and _probe_import(wt_ct, ["pytest"], runner, worktree):
        return {
            "ok": True,
            "cmd": [wt_ct, "-m", "pytest"],
            "env_name": "venv",
            "frozen": False,
            "cached": False,
            "extra_env": None,
        }

    wt_py = _venv_python(worktree / ".venv")
    if wt_py and _probe_import(wt_py, ["pytest"], runner, worktree):
        return {
            "ok": True,
            "cmd": [wt_py, "-m", "pytest"],
            "env_name": "existing_venv",
            "frozen": False,
            "cached": False,
            "extra_env": None,
        }
    wt_pt = _venv_pytest(worktree / ".venv")
    if wt_pt:
        return {
            "ok": True,
            "cmd": [wt_pt],
            "env_name": "existing_venv",
            "frozen": False,
            "cached": False,
            "extra_env": None,
        }

    if repo_dir and repo_dir.is_dir():
        cl_py = _venv_python(repo_dir / ".venv")
        mods = ["pytest"]
        pkg = _project_package_name(worktree)
        if pkg:
            mods.append(pkg)
        if cl_py and _probe_import(cl_py, mods, runner, worktree):
            return {
                "ok": True,
                "cmd": [cl_py, "-m", "pytest"],
                "env_name": "clone_venv",
                "frozen": False,
                "cached": False,
                "extra_env": None,
            }

    if install_on:
        installed = _install_python(
            worktree,
            repo=repo,
            runner=runner,
            which=which,
            timeout_s=install_timeout,
        )
        if installed.get("ok"):
            return installed
        return installed

    path_pt = which("pytest")
    if path_pt:
        return {
            "ok": True,
            "cmd": [str(path_pt)],
            "env_name": "path",
            "frozen": False,
            "cached": False,
            "extra_env": None,
            "probe_on_run": True,
        }

    if detect_pytest(worktree):
        return {"ok": False, "skip_reason": "deps_missing"}
    return {"ok": False, "skip_reason": "no_runner"}


def _install_python(
    worktree: Path,
    *,
    repo: str,
    runner: Runner,
    which: Callable,
    timeout_s: int,
) -> Dict[str, Any]:
    kind, skip = detect_python_manifest(worktree, which=which)
    if skip:
        return {"ok": False, "skip_reason": skip}
    if kind is None:
        return {"ok": False, "skip_reason": "deps_missing"}

    if kind == "poetry":
        return {"ok": False, "skip_reason": "unsupported_installer=poetry"}

    cache = _venv_cache_dir(repo, worktree)

    if kind in ("uv_lock", "uv_pyproject"):
        uv = which("uv")
        if not uv:
            return {"ok": False, "skip_reason": "install_failed"}
        frozen = kind == "uv_lock"
        extra = _uv_env(cache)
        cached_py = _venv_python(cache)
        if cached_py and _probe_import(cached_py, ["pytest"], runner, worktree):
            print("[Execute] python_env=uv_sync frozen=%s cached=true" % str(frozen).lower())
            return {
                "ok": True,
                "cmd": [str(uv), "run"] + (["--frozen"] if frozen else []) + ["pytest"],
                "env_name": "uv_sync",
                "frozen": frozen,
                "cached": True,
                "extra_env": extra,
                "install_cmd": "",
                "install_elapsed_s": 0.0,
            }
        sync_cmd = [str(uv), "sync"] + (["--frozen"] if frozen else [])
        print("[Execute] python_env=uv_sync frozen=%s" % str(frozen).lower())
        t0 = time.monotonic()
        try:
            proc = _run_cmd(sync_cmd, worktree, timeout_s, runner, extra_env=extra)
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - t0
            print("[Execute] skip reason=install_timeout")
            tail = str(getattr(exc, "stdout", "") or "") + str(getattr(exc, "stderr", "") or "")
            return {
                "ok": False,
                "skip_reason": "install_timeout",
                "install_cmd": " ".join(sync_cmd),
                "install_elapsed_s": round(elapsed, 2),
                "raw_tail": tail[-2000:],
                "env_name": "uv_sync",
                "frozen": frozen,
            }
        elapsed = time.monotonic() - t0
        print(f"[Execute] install elapsed={elapsed:.0f}s")
        if int(getattr(proc, "returncode", 1) or 0) != 0:
            out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
            print("[Execute] skip reason=install_failed")
            return {
                "ok": False,
                "skip_reason": "install_failed",
                "install_cmd": " ".join(sync_cmd),
                "install_elapsed_s": round(elapsed, 2),
                "raw_tail": out[-2000:],
                "env_name": "uv_sync",
                "frozen": frozen,
            }
        return {
            "ok": True,
            "cmd": [str(uv), "run"] + (["--frozen"] if frozen else []) + ["pytest"],
            "env_name": "uv_sync",
            "frozen": frozen,
            "cached": False,
            "extra_env": extra,
            "install_cmd": " ".join(sync_cmd),
            "install_elapsed_s": round(elapsed, 2),
        }

    # requirements.txt → venv + pip (no extra packages from the PR)
    py = which("python") or which("python3") or os.environ.get("PYTHON", "") or "python"
    venv_cmd = [str(py), "-m", "venv", str(cache)]
    req = str((worktree / "requirements.txt").as_posix())
    print("[Execute] python_env=venv")
    t0 = time.monotonic()
    try:
        if not _venv_python(cache):
            proc = _run_cmd(venv_cmd, worktree, timeout_s, runner)
            if int(getattr(proc, "returncode", 1) or 0) != 0:
                out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
                print("[Execute] skip reason=install_failed")
                return {
                    "ok": False,
                    "skip_reason": "install_failed",
                    "install_cmd": " ".join(venv_cmd),
                    "install_elapsed_s": round(time.monotonic() - t0, 2),
                    "raw_tail": out[-2000:],
                    "env_name": "venv",
                }
        pip_py = _venv_python(cache)
        if not pip_py:
            print("[Execute] skip reason=install_failed")
            return {"ok": False, "skip_reason": "install_failed", "env_name": "venv"}
        pip_cmd = [pip_py, "-m", "pip", "install", "-r", "requirements.txt"]
        proc = _run_cmd(pip_cmd, worktree, timeout_s, runner)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - t0
        print("[Execute] skip reason=install_timeout")
        tail = str(getattr(exc, "stdout", "") or "") + str(getattr(exc, "stderr", "") or "")
        return {
            "ok": False,
            "skip_reason": "install_timeout",
            "install_cmd": "pip install -r requirements.txt",
            "install_elapsed_s": round(elapsed, 2),
            "raw_tail": tail[-2000:],
            "env_name": "venv",
        }
    elapsed = time.monotonic() - t0
    print(f"[Execute] install elapsed={elapsed:.0f}s")
    if int(getattr(proc, "returncode", 1) or 0) != 0:
        out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
        print("[Execute] skip reason=install_failed")
        return {
            "ok": False,
            "skip_reason": "install_failed",
            "install_cmd": "pip install -r requirements.txt",
            "install_elapsed_s": round(elapsed, 2),
            "raw_tail": out[-2000:],
            "env_name": "venv",
        }
    pip_py = _venv_python(cache)
    _ = req
    return {
        "ok": True,
        "cmd": [str(pip_py), "-m", "pytest"],
        "env_name": "venv",
        "frozen": False,
        "cached": False,
        "extra_env": None,
        "install_cmd": "python -m venv && pip install -r requirements.txt",
        "install_elapsed_s": round(elapsed, 2),
    }


_JS_TEST_MARKERS = (".test.", ".spec.")
_JS_EXTS = (".ts", ".tsx", ".js", ".jsx")


def is_js_test_file(path: str) -> bool:
    p = normalize_path(path).lower()
    base = p.split("/")[-1]
    if not any(base.endswith(ext) for ext in _JS_EXTS):
        return False
    if any(m in base for m in _JS_TEST_MARKERS):
        return True
    return "/__tests__/" in f"/{p}/"


def is_js_file(path: str) -> bool:
    p = normalize_path(path).lower()
    return any(p.endswith(ext) for ext in _JS_EXTS) and not is_lockfile(p)


def collect_js_test_paths(
    findings: List[dict],
    files_changed: List[str],
    max_files: int = 8,
) -> List[str]:
    """related JS tests first, then changed *.test.ts / *.spec.ts. Cap 8."""
    related: List[str] = []
    for f in findings or []:
        src = normalize_path(str(f.get("file") or ""))
        if is_js_test_file(src) and not is_lockfile(src):
            related.append(src)
        for p in f.get("related_tests") or []:
            if is_js_test_file(str(p)) and not is_lockfile(str(p)):
                related.append(normalize_path(str(p)))
    changed = [
        normalize_path(p)
        for p in (files_changed or [])
        if is_js_test_file(p) and not is_lockfile(p)
    ]
    return list(dict.fromkeys(related + changed))[:max_files]


def find_js_package_root(worktree: Path, rel: Optional[str] = None) -> Optional[Path]:
    """package.json at repo root, app/, or walking up from the test file."""
    candidates: List[Path] = []
    if rel:
        cur = (worktree / rel).parent
        root = worktree.resolve()
        try:
            cur.resolve().relative_to(root)
        except ValueError:
            cur = worktree
        while True:
            candidates.append(cur)
            if cur.resolve() == root:
                break
            if cur.parent == cur:
                break
            cur = cur.parent
    candidates.extend([worktree / "app", worktree])
    seen = set()
    for c in candidates:
        key = str(c.resolve()) if c.exists() else str(c)
        if key in seen:
            continue
        seen.add(key)
        if (c / "package.json").is_file():
            return c
    return None


def _read_package_json(pkg_dir: Path) -> dict:
    p = pkg_dir / "package.json"
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="ignore") or "{}")
    except (OSError, json.JSONDecodeError):
        return {}


def detect_js_runner(
    pkg_dir: Path, which: Callable = shutil.which
) -> Dict[str, Any]:
    """Vitest/Jest file-arg runners only. Full vite app → js_runner_not_pathable."""
    if not (pkg_dir / "package.json").is_file():
        return {"ok": False, "skip_reason": "no_js_runner"}
    data = _read_package_json(pkg_dir)
    scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
    deps: Dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            deps.update(block)
    test_script = str(scripts.get("test") or "").strip().lower()
    has_vitest = "vitest" in deps or "vitest" in test_script
    has_jest = "jest" in deps or (test_script.startswith("jest") or " jest" in f" {test_script}")
    npx = which("npx")
    npm = which("npm")
    pnpm = which("pnpm")
    yarn = which("yarn")

    if has_vitest:
        if npx:
            return {"ok": True, "kind": "vitest", "prefix": [str(npx), "vitest", "run"]}
        if npm:
            return {"ok": True, "kind": "vitest", "prefix": [str(npm), "exec", "--", "vitest", "run"]}
        return {"ok": False, "skip_reason": "no_js_runner"}
    if has_jest:
        if npx:
            return {"ok": True, "kind": "jest", "prefix": [str(npx), "jest"]}
        if npm:
            return {"ok": True, "kind": "jest", "prefix": [str(npm), "exec", "--", "jest"]}
        return {"ok": False, "skip_reason": "no_js_runner"}

    if test_script:
        # Cannot pass file args to a generic vite/webpack app test script.
        return {"ok": False, "skip_reason": "js_runner_not_pathable"}

    lock_npm = (pkg_dir / "package-lock.json").is_file()
    if lock_npm and npm and not test_script:
        return {"ok": False, "skip_reason": "no_js_runner"}
    if (pkg_dir / "pnpm-lock.yaml").is_file() and pnpm:
        return {"ok": False, "skip_reason": "js_runner_not_pathable"}
    if (pkg_dir / "yarn.lock").is_file() and yarn:
        return {"ok": False, "skip_reason": "js_runner_not_pathable"}
    return {"ok": False, "skip_reason": "no_js_runner"}


def prepare_js_env(
    pkg_dir: Path,
    state: dict,
    *,
    runner: Runner,
    which: Callable,
) -> Dict[str, Any]:
    """npm ci --ignore-scripts only with --execute-install. No PR-named packages."""
    detected = detect_js_runner(pkg_dir, which=which)
    if not detected.get("ok"):
        return detected
    allow_scripts = state.get("execute_allow_npm_scripts") is True or (
        getattr(settings, "execute_allow_npm_scripts", False) is True
    )
    node_modules = pkg_dir / "node_modules"
    if node_modules.is_dir():
        return {**detected, "install_cmd": "", "install_elapsed_s": 0.0}
    if not _install_enabled(state):
        return {"ok": False, "skip_reason": "deps_missing"}
    npm = which("npm")
    if not npm:
        return {"ok": False, "skip_reason": "js_install_failed"}
    cmd = [str(npm), "ci"]
    if not allow_scripts:
        cmd.append("--ignore-scripts")
    timeout_s = int(
        state.get("execute_install_timeout_s")
        or getattr(settings, "execute_install_timeout_s", 180)
    )
    print(f"[Execute] js_cwd={pkg_dir.name}")
    print(f"[Execute] js_install={' '.join(cmd)}")
    t0 = time.monotonic()
    try:
        proc = _run_cmd(cmd, pkg_dir, timeout_s, runner)
    except subprocess.TimeoutExpired:
        print("[Execute] js skip reason=install_timeout")
        return {
            "ok": False,
            "skip_reason": "install_timeout",
            "install_cmd": " ".join(cmd),
            "install_elapsed_s": round(time.monotonic() - t0, 2),
        }
    elapsed = time.monotonic() - t0
    if int(getattr(proc, "returncode", 1) or 0) != 0:
        print("[Execute] js skip reason=js_install_failed")
        out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
        return {
            "ok": False,
            "skip_reason": "js_install_failed",
            "install_cmd": " ".join(cmd),
            "install_elapsed_s": round(elapsed, 2),
            "raw_tail": out[-2000:],
        }
    print(f"[Execute] js_install elapsed={elapsed:.0f}s")
    return {
        **detected,
        "install_cmd": " ".join(cmd),
        "install_elapsed_s": round(elapsed, 2),
    }


def run_js(
    prefix: List[str],
    paths: List[str],
    cwd: Path,
    timeout_s: int,
    runner: Runner,
) -> Tuple[Optional[subprocess.CompletedProcess], Optional[str], float, str, List[str]]:
    cmd = [*prefix, *paths]
    print(f"[Execute] js_cwd={cwd.name}")
    print(f"[Execute] js_cmd={' '.join(cmd)}")
    t0 = time.monotonic()
    try:
        proc = _run_cmd(cmd, cwd, timeout_s, runner)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - t0
        tail = str(getattr(exc, "stdout", "") or "") + str(getattr(exc, "stderr", "") or "")
        return None, "timeout", elapsed, tail[-2000:], cmd
    elapsed = time.monotonic() - t0
    out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
    return proc, None, elapsed, out, cmd


def _rel_to_pkg(rel: str, pkg_dir: Path, worktree: Path) -> str:
    full = (worktree / rel).resolve()
    try:
        return full.relative_to(pkg_dir.resolve()).as_posix()
    except ValueError:
        return rel


def run_js_slice(
    worktree: Path,
    findings: List[dict],
    files_changed: List[str],
    state: dict,
    *,
    runner: Runner,
    which: Callable,
    timeout_s: int,
    max_files: int,
) -> ExecutionSlice:
    allow = state.get("execute_allow_npm")
    if allow is False or (
        allow is None and getattr(settings, "execute_allow_npm", True) is False
    ):
        print("[Execute] js skip reason=js_disabled")
        return ExecutionSlice(skipped=True, skip_reason="js_disabled")

    wanted = collect_js_test_paths(findings, files_changed, max_files=max_files)
    if not wanted:
        print("[Execute] js skip reason=no_js_targets")
        return ExecutionSlice(skipped=True, skip_reason="no_js_targets")

    jailed: List[str] = []
    for rel in wanted:
        safe = jail_relpath(worktree, rel)
        if safe:
            jailed.append(safe)
    if not jailed:
        print("[Execute] js skip reason=no_js_targets")
        return ExecutionSlice(skipped=True, skip_reason="no_js_targets")

    pkg_dir = find_js_package_root(worktree, jailed[0])
    if pkg_dir is None:
        print("[Execute] js skip reason=no_js_runner")
        return ExecutionSlice(skipped=True, skip_reason="no_js_runner", ran_paths=jailed)

    prepared = prepare_js_env(pkg_dir, state, runner=runner, which=which)
    if not prepared.get("ok"):
        reason = str(prepared.get("skip_reason") or "no_js_runner")
        print(f"[Execute] js skip reason={reason}")
        return ExecutionSlice(
            skipped=True,
            skip_reason=reason,
            cwd=str(pkg_dir),
            ran_paths=jailed,
            install_cmd=str(prepared.get("install_cmd") or ""),
            install_elapsed_s=float(prepared.get("install_elapsed_s") or 0.0),
            raw_tail=str(prepared.get("raw_tail") or ""),
        )

    rel_files = [_rel_to_pkg(p, pkg_dir, worktree) for p in jailed]
    prefix = list(prepared.get("prefix") or [])
    proc, err, elapsed, out, cmd = run_js(prefix, rel_files, pkg_dir, timeout_s, runner)
    cmd_s = " ".join(cmd)
    if err == "timeout":
        print("[Execute] js skip reason=timeout")
        return ExecutionSlice(
            skipped=True,
            skip_reason="timeout",
            cmd=cmd_s,
            cwd=str(pkg_dir),
            elapsed_s=round(elapsed, 2),
            raw_tail=out,
            ran_paths=jailed,
            env=str(prepared.get("kind") or ""),
        )
    exit_code = int(getattr(proc, "returncode", 1) or 0)
    parsed = parse_pytest_output(out, exit_code)
    print(f"[Execute] js_exit={exit_code}")
    return ExecutionSlice(
        skipped=False,
        skip_reason=None,
        cmd=cmd_s,
        cwd=str(pkg_dir),
        exit_code=exit_code,
        elapsed_s=round(elapsed, 2),
        passed=parsed["passed"],
        failed=parsed["failed"],
        failed_names=list(parsed["failed_names"] or []),
        raw_tail=out[-2000:],
        ran_paths=jailed,
        env=str(prepared.get("kind") or ""),
        install_cmd=str(prepared.get("install_cmd") or ""),
        install_elapsed_s=float(prepared.get("install_elapsed_s") or 0.0),
    )


def run_pytest(
    prefix: List[str],
    paths: List[str],
    cwd: Path,
    timeout_s: int,
    runner: Runner,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[subprocess.CompletedProcess], Optional[str], float, str]:
    cmd = [*prefix, *paths, "-q", "--tb=line"]
    print(f"[Execute] cmd={' '.join(cmd)}")
    t0 = time.monotonic()
    try:
        proc = _run_cmd(cmd, cwd, timeout_s, runner, extra_env=extra_env)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - t0
        tail = str(getattr(exc, "stdout", "") or "") + str(getattr(exc, "stderr", "") or "")
        return None, "timeout", elapsed, tail[-2000:]
    elapsed = time.monotonic() - t0
    out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
    return proc, None, elapsed, out


def _run_python_slice(
    worktree: Path,
    repo_dir: Path,
    state: dict,
    wanted: List[str],
    *,
    runner: Runner,
    which: Callable,
    timeout_s: int,
) -> ExecutionSlice:
    prepared = prepare_python_env(
        worktree, repo_dir, state, runner=runner, which=which
    )
    jailed: List[str] = []
    for rel in wanted:
        safe = jail_relpath(worktree, rel)
        if safe:
            jailed.append(safe)
    if not prepared.get("ok"):
        reason = str(prepared.get("skip_reason") or "no_runner")
        if reason == "deps_missing":
            print("[Execute] skip reason=deps_missing (pass --execute-install to sync)")
        elif reason not in ("install_failed", "install_timeout"):
            print(f"[Execute] skip reason={reason}")
        return ExecutionSlice(
            skipped=True,
            skip_reason=reason,
            cwd=str(worktree),
            env=str(prepared.get("env_name") or ""),
            frozen=bool(prepared.get("frozen")),
            install_cmd=str(prepared.get("install_cmd") or ""),
            install_elapsed_s=float(prepared.get("install_elapsed_s") or 0.0),
            raw_tail=str(prepared.get("raw_tail") or ""),
            ran_paths=jailed,
        )
    if not jailed:
        print("[Execute] skip reason=missing_test_file")
        return ExecutionSlice(
            skipped=True, skip_reason="missing_test_file", cwd=str(worktree)
        )

    prefix = list(prepared.get("cmd") or ["pytest"])
    extra_env = prepared.get("extra_env")
    env_name = str(prepared.get("env_name") or "")
    if env_name and env_name != "path":
        extra = f" frozen={str(bool(prepared.get('frozen'))).lower()}" if env_name == "uv_sync" else ""
        cached = " cached=true" if prepared.get("cached") else ""
        if not prepared.get("install_cmd"):
            print(f"[Execute] python_env={env_name}{extra}{cached}".rstrip())

    proc, err, elapsed, out = run_pytest(
        prefix, jailed, worktree, timeout_s, runner, extra_env=extra_env
    )
    cmd_s = " ".join([*prefix, *jailed, "-q", "--tb=line"])
    if err == "timeout":
        print("[Execute] skip reason=timeout")
        return ExecutionSlice(
            skipped=True,
            skip_reason="timeout",
            cmd=cmd_s,
            cwd=str(worktree),
            elapsed_s=round(elapsed, 2),
            raw_tail=out,
            ran_paths=jailed,
            env=env_name,
        )
    exit_code = int(getattr(proc, "returncode", 1) or 0)
    if bool(prepared.get("probe_on_run")) and (
        "ModuleNotFoundError" in out or "No module named" in out
    ):
        print("[Execute] skip reason=deps_missing (pass --execute-install to sync)")
        return ExecutionSlice(
            skipped=True,
            skip_reason="deps_missing",
            cmd=cmd_s,
            cwd=str(worktree),
            exit_code=exit_code,
            elapsed_s=round(elapsed, 2),
            raw_tail=out[-2000:],
            ran_paths=jailed,
            env=env_name,
        )
    parsed = parse_pytest_output(out, exit_code)
    failed_n = parsed["failed"]
    passed_n = parsed["passed"]
    print(
        f"[Execute] exit={exit_code} elapsed={elapsed:.1f}s "
        f"passed={passed_n} failed={failed_n}"
    )
    return ExecutionSlice(
        skipped=False,
        skip_reason=None,
        cmd=cmd_s,
        cwd=str(worktree),
        exit_code=exit_code,
        elapsed_s=round(elapsed, 2),
        passed=passed_n,
        failed=failed_n,
        failed_names=list(parsed["failed_names"] or []),
        raw_tail=out[-2000:],
        ran_paths=jailed,
        env=env_name,
        frozen=bool(prepared.get("frozen")),
        cached=bool(prepared.get("cached")),
        install_cmd=str(prepared.get("install_cmd") or ""),
        install_elapsed_s=float(prepared.get("install_elapsed_s") or 0.0),
    )


def _record_from_slices(
    py: ExecutionSlice, js: ExecutionSlice, worktree: Path
) -> ExecutionRecord:
    py_ran = not py.skipped
    js_ran = not js.skipped
    skipped = not (py_ran or js_ran)
    lead = py if py_ran or not js_ran else js
    reason = (py.skip_reason or js.skip_reason) if skipped else None
    ran = list(py.ran_paths or []) + [p for p in (js.ran_paths or []) if p not in (py.ran_paths or [])]
    return ExecutionRecord(
        enabled=True,
        skipped=skipped,
        skip_reason=reason,
        cmd=lead.cmd,
        cwd=lead.cwd or str(worktree),
        exit_code=lead.exit_code,
        elapsed_s=float(py.elapsed_s or 0) + float(js.elapsed_s or 0),
        passed=py.passed if py_ran else (js.passed if js_ran else None),
        failed=(py.failed if py_ran else None) if py_ran else (js.failed if js_ran else None),
        failed_names=list(py.failed_names or []) + list(js.failed_names or []),
        raw_tail=(py.raw_tail or "")[-1000:] + (js.raw_tail or "")[-1000:],
        ran_paths=ran,
        python_env=py.env,
        python=py,
        js=js,
    )


def execute_tests_node(
    state: dict,
    *,
    runner: Runner = subprocess.run,
    checkout: Optional[Callable] = None,
    which: Callable = shutil.which,
) -> dict:
    """LangGraph node: after verify_findings, before critic. Default skip."""
    if not _env_enabled(state) and _install_requested(state):
        print("[Execute] skip reason=install_ignored_flag_off")

    skip = execution_skip_reason(state)
    if skip:
        print(f"[Execute] skip reason={skip}")
        rec = ExecutionRecord(enabled=_env_enabled(state), skipped=True, skip_reason=skip)
        return {
            "execution_report": rec.model_dump(),
            "traces": [{"agent": "ExecuteTests", "output": f"skip reason={skip}"}],
        }

    facts = state.get("pr_facts") or {}
    files_changed = list(facts.get("files_changed") or state.get("files_changed") or [])
    findings = list(state.get("validated_findings") or state.get("findings") or [])
    timeout_s = int(state.get("execute_timeout_s") or getattr(settings, "execute_timeout_s", 120))
    max_files = int(state.get("execute_max_files") or getattr(settings, "execute_max_files", 8))
    repo = state.get("repo") or ""
    sha = str(state.get("pr_head_sha") or "")
    number = state.get("number") or 0

    wanted_py = collect_test_paths(findings, files_changed, max_files=max_files)
    wanted_js = collect_js_test_paths(findings, files_changed, max_files=max_files)
    if not wanted_py and not wanted_js:
        print("[Execute] skip reason=missing_test_file")
        rec = ExecutionRecord(enabled=True, skipped=True, skip_reason="missing_test_file")
        return _stamp_skip(state, rec, findings)

    repo_dir = resolve_repo_dir(repo)
    dest = Path("tmp") / "codeturtle-exec" / f"{repo_to_folder(repo)}_{number}"
    checkout_fn = checkout or checkout_pr_head
    ok, why = checkout_fn(repo_dir, sha, dest, runner=runner)
    if not ok:
        print(f"[Execute] skip reason={why or 'checkout_failed'}")
        rec = ExecutionRecord(enabled=True, skipped=True, skip_reason=why or "checkout_failed")
        return _stamp_skip(state, rec, findings)

    worktree = dest
    try:
        if wanted_py:
            py_slice = _run_python_slice(
                worktree,
                repo_dir,
                state,
                wanted_py,
                runner=runner,
                which=which,
                timeout_s=timeout_s,
            )
        else:
            py_slice = ExecutionSlice(skipped=True, skip_reason="missing_test_file")
        js_slice = run_js_slice(
            worktree,
            findings,
            files_changed,
            state,
            runner=runner,
            which=which,
            timeout_s=timeout_s,
            max_files=max_files,
        )
        rec = _record_from_slices(py_slice, js_slice, worktree)
        if rec.skipped:
            return _stamp_skip(state, rec, findings)
        stamped = _stamp_findings(findings, rec)
        result: Dict[str, Any] = {
            "validated_findings": stamped,
            "findings": stamped,
            "execution_report": rec.model_dump(),
            "traces": [
                {
                    "agent": "ExecuteTests",
                    "output": (
                        f"py skipped={py_slice.skipped} js skipped={js_slice.skipped} "
                        f"exit={rec.exit_code} passed={rec.passed} failed={rec.failed}"
                    ),
                }
            ],
        }
        vrep = state.get("verification_report")
        if isinstance(vrep, dict) and vrep:
            vrep = dict(vrep)
            understanding = state.get("pr_understanding") or {}
            risk = ""
            if isinstance(understanding, dict):
                risk = str(understanding.get("risk_level") or "")
            plan = state.get("review_plan") or {}
            if isinstance(plan, dict) and plan.get("risk_level"):
                risk = str(plan.get("risk_level") or risk)
            vrep["suggested_recommendation"] = recommendation_from_verification(
                stamped,
                classification=str(facts.get("classification") or ""),
                risk=risk or "medium",
                execution=rec.model_dump(),
            )
            result["verification_report"] = vrep
        return result
    finally:
        _cleanup_worktree(repo_dir, dest, runner=runner)


def _stamp_skip(state: dict, rec: ExecutionRecord, findings: List[dict]) -> dict:
    stamped = []
    for f in findings:
        d = dict(f) if isinstance(f, dict) else {}
        d.setdefault("tests_run", False)
        d.setdefault("tests_passed", None)
        stamped.append(d)
    return {
        "validated_findings": stamped,
        "findings": stamped,
        "execution_report": rec.model_dump(),
        "traces": [
            {
                "agent": "ExecuteTests",
                "output": f"skip reason={rec.skip_reason}",
            }
        ],
    }


def _slice_hit(sl: ExecutionSlice, related: List[str], src: str) -> bool:
    if sl.skipped:
        return False
    ran_l = {normalize_path(p).lower() for p in sl.ran_paths or []}
    ran_bases = {p.split("/")[-1].lower() for p in ran_l}
    hit = any(
        r.lower() in ran_l or r.split("/")[-1].lower() in ran_bases for r in related
    )
    if not related:
        hit = src.lower() in ran_l or src.split("/")[-1].lower() in ran_bases
    return hit


def _slice_ok(sl: ExecutionSlice) -> bool:
    return (not sl.skipped) and sl.exit_code == 0 and not sl.failed


def _stamp_findings(
    findings: List[dict],
    rec: ExecutionRecord,
) -> List[dict]:
    summaries = []
    if rec.python and not rec.python.skipped:
        summaries.append(
            f"{rec.python.cmd} exit={rec.python.exit_code} "
            f"{rec.python.passed if rec.python.passed is not None else '?'} passed"
        )
    if rec.js and not rec.js.skipped:
        summaries.append(f"{rec.js.cmd} exit={rec.js.exit_code}")
    summary = "; ".join(summaries) if summaries else (
        f"{rec.cmd} exit={rec.exit_code} "
        f"{rec.passed if rec.passed is not None else '?'} passed"
    )
    out: List[dict] = []
    for f in findings or []:
        d = dict(f) if isinstance(f, dict) else {}
        related = [normalize_path(str(x)) for x in (d.get("related_tests") or [])]
        src = normalize_path(str(d.get("file") or ""))
        py_hit = _slice_hit(rec.python, related, src)
        js_hit = _slice_hit(rec.js, related, src)
        hit = py_hit or js_hit
        d["tests_run"] = bool(hit)
        if hit:
            oks = []
            if py_hit:
                oks.append(_slice_ok(rec.python))
            if js_hit:
                oks.append(_slice_ok(rec.js))
            tests_ok = all(oks) if oks else False
            d["tests_passed"] = bool(tests_ok)
            d["execution_summary"] = summary
            if tests_ok and looks_like_testing_nit(d):
                d = adjust_testing_nit(d, tests_touched=True)
        else:
            d["tests_passed"] = None
            d["tests_run"] = False
        out.append(d)
    return out


def _cleanup_worktree(repo_dir: Path, dest: Path, runner: Runner = subprocess.run) -> None:
    try:
        runner(
            ["git", "-C", str(repo_dir), "worktree", "remove", "--force", str(dest)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass
    shutil.rmtree(dest, ignore_errors=True)
