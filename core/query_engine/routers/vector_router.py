"""Vector router — wired in Phase 7 Step 4."""

class VectorRouter:
    def __init__(self, repo_name: str, kb=None):
        self.repo_name = repo_name
        self.kb = kb