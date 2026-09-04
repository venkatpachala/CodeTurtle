"""Load and merge .codeturtle.yaml. Missing file = current defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RepoConfigError(Exception):
    """Invalid YAML or types — fail review startup, do not ignore the file."""


class RepoConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    skip_drafts: Optional[bool] = None
    skip_authors: List[str] = Field(default_factory=list)
    ignore_paths: List[str] = Field(default_factory=list)
    inline_max: Optional[int] = None
    inline_lockfile: Optional[bool] = None
    post_on_github: bool = False
    execute_tests: Optional[bool] = None
    execute_install: Optional[bool] = None
    model: Optional[str] = None
    llm_backend: Optional[str] = None
    coverage_merge_min: Optional[float] = None


@dataclass
class EffectiveReviewConfig:
    skip_drafts: bool = False
    skip_authors: List[str] = field(default_factory=list)
    ignore_paths: List[str] = field(default_factory=list)
    inline_max: int = 8
    inline_lockfile: bool = False
    execute_tests: bool = False
    execute_install: bool = False
    model: str = ""
    llm_backend: str = ""
    post_on_github: bool = False
    coverage_merge_min: float = 0.5
    config_path: Optional[Path] = None


def find_config_path(
    cli_path: Optional[str] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
) -> Optional[Path]:
    """`--config` → CODETURTLE_CONFIG → ./.codeturtle.yaml|.yml in cwd."""
    if cli_path:
        p = Path(cli_path)
        if not p.is_file():
            raise RepoConfigError(f"--config file not found: {p}")
        return p
    env = environ if environ is not None else os.environ
    env_path = (env.get("CODETURTLE_CONFIG") or "").strip()
    if env_path:
        p = Path(env_path)
        return p if p.is_file() else None
    root = Path(cwd or Path.cwd())
    for name in (".codeturtle.yaml", ".codeturtle.yml"):
        p = root / name
        if p.is_file():
            return p
    return None


def load_repo_config(path: Optional[Path]) -> Optional[RepoConfig]:
    if path is None:
        return None
    try:
        import yaml
    except ImportError as exc:
        raise RepoConfigError("PyYAML is required to load .codeturtle.yaml") from exc
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RepoConfigError(f"cannot read {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RepoConfigError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise RepoConfigError(f"{path} must be a mapping, got {type(data).__name__}")
    try:
        return RepoConfig.model_validate(data)
    except ValidationError as exc:
        raise RepoConfigError(f"invalid .codeturtle.yaml in {path}:\n{exc}") from exc


def merge_review_config(
    *,
    repo: Optional[RepoConfig] = None,
    cli_execute_tests: bool = False,
    cli_execute_install: bool = False,
    settings: Any = None,
    config_path: Optional[Path] = None,
) -> EffectiveReviewConfig:
    """Settings/.env < YAML < CLI execute flags. Dry-run is not merged here."""
    if settings is None:
        from config import settings as _s

        settings = _s
    out = EffectiveReviewConfig(
        inline_max=int(getattr(settings, "inline_max", 8) or 8),
        inline_lockfile=bool(getattr(settings, "inline_lockfile", False)),
        execute_tests=bool(getattr(settings, "execute_tests", False)),
        execute_install=bool(getattr(settings, "execute_install", False)),
        model=str(getattr(settings, "ollama_model", "") or ""),
        llm_backend=str(getattr(settings, "llm_backend", "") or ""),
        coverage_merge_min=float(getattr(settings, "coverage_merge_min", 0.5) or 0.5),
        config_path=config_path,
    )
    if repo is not None:
        if repo.skip_drafts is not None:
            out.skip_drafts = bool(repo.skip_drafts)
        out.skip_authors = [str(a) for a in (repo.skip_authors or []) if a]
        out.ignore_paths = [str(p) for p in (repo.ignore_paths or []) if p]
        if repo.inline_max is not None:
            out.inline_max = int(repo.inline_max)
        if repo.inline_lockfile is not None:
            out.inline_lockfile = bool(repo.inline_lockfile)
        if repo.execute_tests is True:
            out.execute_tests = True
        if repo.execute_install is True:
            out.execute_install = True
        if repo.model:
            out.model = str(repo.model)
        if repo.llm_backend:
            out.llm_backend = str(repo.llm_backend)
        out.post_on_github = bool(repo.post_on_github)
        if repo.coverage_merge_min is not None:
            out.coverage_merge_min = float(repo.coverage_merge_min)
    if cli_execute_tests:
        out.execute_tests = True
    if cli_execute_install:
        out.execute_install = True
    return out


def review_skip_reason(
    *,
    author: str = "",
    draft: bool = False,
    cfg: Optional[EffectiveReviewConfig] = None,
) -> Optional[str]:
    cfg = cfg or EffectiveReviewConfig()
    a = (author or "").strip().lower()
    if a and any(a == str(x).strip().lower() for x in cfg.skip_authors):
        return "skip_author"
    if draft and cfg.skip_drafts:
        return "draft"
    return None


def yaml_cannot_force_post(*, dry_run: bool, comment: bool, post_on_github: bool) -> bool:
    """YAML post_on_github never overrides CLI dry-run."""
    from core.github_review import should_post

    if should_post(dry_run=dry_run, comment=comment):
        return True
    _ = post_on_github
    return False
