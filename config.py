from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from dotenv import load_dotenv
import os

# Explicitly load .env
load_dotenv()

class Settings(BaseSettings):
    # LLM Configuration
    llm_backend: str = "ollama"                    # ← Added this
    ollama_model: str = "qwen2.5:7b"
    ollama_base_url: str = "http://localhost:11434"

    # GitHub
    github_token: str = ""

    # Paths
    memory_path: str = "~/.reviewforge/memory"
    traces_path: str = "~/.reviewforge/traces"

    model_config = ConfigDict(
        env_file = ".env",
        extra = "ignore"          # ← This allows extra variables without error
    )


# Create the settings instance
settings = Settings()