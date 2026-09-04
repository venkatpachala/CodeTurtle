from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from dotenv import load_dotenv
import os

# Explicitly load .env
load_dotenv()

class Settings(BaseSettings):
    # LLM Configuration
    llm_backend: str = "ollama"                    # ← Added this
    ollama_model: str = "qwen2.5-coder:7b"
    ollama_base_url: str = "http://localhost:11434"

    # GitHub
    github_token: str = ""

    # Paths
    memory_path: str = "~/.codeturrle/memory"
    traces_path: str = "~/.codeturrle/traces"

    model_config = ConfigDict(
        env_file = ".env",
        extra = "ignore"          # ← This allows extra variables without error
        
    )
    # Graphify (structural knowledge)
    graphify_enabled: bool = False
    graphify_graph_path: str = "graphify-out/graph.json"
    graphify_http_url: str = "http://localhost:8080/mcp"
    graphify_python: str = "python"
    graphify_project_path: str = ""
    # config
    repos_root: str = "repos"
    graphify_graph_filename: str = "graphify-out/graph.json"
    graphify_transport: str = "http"   # preferred
    graphify_only_retrieval: bool = True
    neo4j_enabled: bool = False

    # Phase 4.3 — optional isolated pytest (off by default)
    execute_tests: bool = False
    execute_timeout_s: int = 120
    execute_max_files: int = 8
    # 4.3b/c — install in the PR worktree (off by default; implies network)
    execute_install: bool = False
    execute_install_timeout_s: int = 180
    execute_allow_npm: bool = True
    execute_allow_npm_scripts: bool = False
    execute_network: bool = False

    # Phase 6.2 — inline review comments (post path only)
    inline_max: int = 8
    inline_lockfile: bool = False

# Create the settings instance
settings = Settings()