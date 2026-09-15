"""User config under ~/.codeturtle (not a cwd .env)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

CONFIG_NAME = "config.toml"
REPOS_DIRNAME = "repos"
SESSION_NAME = "current_session"

_TOML_KEYS = (
    "github_token",
    "ollama_model",
    "llm_backend",
    "ollama_base_url",
    "openai_api_key",
)

_ENV_FOR_KEY = {
    "github_token": "GITHUB_TOKEN",
    "ollama_model": "OLLAMA_MODEL",
    "llm_backend": "LLM_BACKEND",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "openai_api_key": "OPENAI_API_KEY",
}


def home_dir() -> Path:
    raw = (os.environ.get("CODETURTLE_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".codeturtle").resolve()


def config_path() -> Path:
    return home_dir() / CONFIG_NAME


def repos_dir() -> Path:
    raw = (os.environ.get("CODETURTLE_REPOS_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return home_dir() / REPOS_DIRNAME


def session_file() -> Path:
    if os.environ.get("GITHUB_ACTIONS"):
        return Path(".current_session")
    return home_dir() / SESSION_NAME


def ensure_home() -> Path:
    p = home_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_user_config(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or config_path()
    if not p.is_file():
        return {}
    try:
        import tomllib

        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in _TOML_KEYS if k in data and data[k] not in (None, "")}


def dumps_toml(data: Mapping[str, Any]) -> str:
    lines = [
        "# CodeTurtle user config. Written by `codeturtle` (first-run wizard).",
        "# Environment variables override these values.",
        "",
    ]
    for key in _TOML_KEYS:
        if key not in data or data[key] in (None, ""):
            continue
        val = data[key]
        if isinstance(val, bool):
            lines.append(f"{key} = {'true' if val else 'false'}")
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            lines.append(f"{key} = {val}")
        else:
            text = str(val).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{text}"')
    return "\n".join(lines).rstrip() + "\n"


def save_user_config(updates: Mapping[str, Any], path: Optional[Path] = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    current = load_user_config(p)
    for key in _TOML_KEYS:
        if key in updates and updates[key] not in (None, ""):
            current[key] = updates[key]
    p.write_text(dumps_toml(current), encoding="utf-8")
    return p


def apply_user_config_to_environ(
    data: Optional[Mapping[str, Any]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Copy config.toml into os.environ only for keys that are not already set."""
    env = os.environ if environ is None else environ
    blob = dict(data) if data is not None else load_user_config()
    for key, env_key in _ENV_FOR_KEY.items():
        val = blob.get(key)
        if not val:
            continue
        if not str(env.get(env_key) or "").strip():
            env[env_key] = str(val)  # type: ignore[index]


def apply_user_config_to_settings(settings_obj: Any) -> None:
    data = load_user_config()
    if data.get("github_token") and not getattr(settings_obj, "github_token", ""):
        settings_obj.github_token = str(data["github_token"])
    if data.get("ollama_model"):
        settings_obj.ollama_model = str(data["ollama_model"])
    if data.get("llm_backend"):
        settings_obj.llm_backend = str(data["llm_backend"])
    if data.get("ollama_base_url"):
        settings_obj.ollama_base_url = str(data["ollama_base_url"])


def detect_github_token(
    environ: Optional[Mapping[str, str]] = None,
    *,
    gh_token: Optional[str] = None,
) -> str:
    """config.toml / env, then `gh auth token`. Does not prompt."""
    env = os.environ if environ is None else environ
    for key in ("CODETURTLE_GITHUB_TOKEN", "GITHUB_TOKEN"):
        v = str(env.get(key) or "").strip()
        if v:
            return v
    cfg = load_user_config()
    v = str(cfg.get("github_token") or "").strip()
    if v:
        return v
    if gh_token is not None:
        return str(gh_token).strip()
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return ""
