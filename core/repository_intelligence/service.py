class RepositoryIntelligenceService:
    def index(self, repo_name: str, local_path: str, *, force: bool = False) -> RepositorySnapshot:
        # 1 compile
        # 2 persist snapshot
        # 3 graph build + imports
        # 4 embed/index to Qdrant
        return snapshot