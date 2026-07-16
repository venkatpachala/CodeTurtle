from pathlib import Path
import json
from datetime import datetime
from typing import Optional

from core.repository_model import RepositoryModel


class RepositoryPersistence:
    """Handles persistence of the RepositoryModel outside the cloned repository."""

    def __init__(self, repo_name: str):
        self.workspace = Path(".codeturtle/repositories") / repo_name.replace("/", "_")
        self.workspace.mkdir(parents=True, exist_ok=True)

    def save_repository_model(self, repository_model: RepositoryModel):
        """Save RepositoryModel to .codeturtle workspace."""
        path = self.workspace / "repository_model.json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(repository_model.model_dump_json(indent=2))

    def load_repository_model(self) -> Optional[RepositoryModel]:
        """Load previously saved RepositoryModel."""
        path = self.workspace / "repository_model.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RepositoryModel.model_validate(data)
        return None