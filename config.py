from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from dotenv import load_dotenv
import os
import sys

# ~/.codeturtle/config.toml first, then cwd .env (does not override existing env).
from core.user_config import apply_user_config_to_environ, home_dir, repos_dir

apply_user_config_to_environ()
load_dotenv()


class Settings(BaseSettings):
    # LLM Configuration
    llm_backend: str = "ollama"
    ollama_model: str = "qwen2.5:7b"
    ollama_base_url: str = "http://localhost:11434"

    # GitHub
    github_token: str = ""

    # Paths
    memory_path: str = str(home_dir() / "memory")
    traces_path: str = str(home_dir() / "traces")

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore",
    )
    # Graphify (structural knowledge)
    graphify_enabled: bool = False
    graphify_graph_path: str = "graphify-out/graph.json"
    graphify_http_url: str = "http://localhost:8080/mcp"
    graphify_python: str = sys.executable
    graphify_project_path: str = ""
    # empty = ~/.codeturtle/repos
    repos_root: str = ""
    graphify_graph_filename: str = "graphify-out/graph.json"
    graphify_transport: str = "stdio"
    graphify_only_retrieval: bool = True
    neo4j_enabled: bool = False

    # Phase 4.3 — optional isolated pytest (off by default)
    execute_tests: bool = False
    execute_timeout_s: int = 120
    execute_max_files: int = 8
    execute_install: bool = False
    execute_install_timeout_s: int = 180
    execute_allow_npm: bool = True
    execute_allow_npm_scripts: bool = False
    execute_network: bool = False

    inline_max: int = 8
    inline_lockfile: bool = False

    coverage_merge_min: float = 0.5


settings = Settings()
if not (getattr(settings, "repos_root", None) or "").strip():
    settings.repos_root = str(repos_dir())
