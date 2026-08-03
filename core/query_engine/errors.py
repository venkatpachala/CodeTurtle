"""Query Engine errors — fail loud, never silent empty on missing repo."""


class QueryEngineError(Exception):
    """Base error for Repository Query Engine."""


class RepoNotIndexedError(QueryEngineError):
    def __init__(self, repo_name: str):
        self.repo_name = repo_name
        super().__init__(
            f"Repository '{repo_name}' is not indexed. "
            f"Run: python -m cli.main add-repo {repo_name}"
        )


class SymbolNotFoundError(QueryEngineError):
    def __init__(self, name: str, path: str | None = None):
        self.name = name
        self.path = path
        loc = f" in {path}" if path else ""
        super().__init__(f"Symbol '{name}' not found{loc}")


class FileNotFoundError(QueryEngineError):
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"File not found in repository model: {path}")


class GraphUnavailableError(QueryEngineError):
    def __init__(self, detail: str = ""):
        msg = "Neo4j graph is unavailable"
        if detail:
            msg = f"{msg}: {detail}"
        super().__init__(msg)


class VectorUnavailableError(QueryEngineError):
    def __init__(self, detail: str = ""):
        msg = "Vector store (Qdrant) is unavailable"
        if detail:
            msg = f"{msg}: {detail}"
        super().__init__(msg)