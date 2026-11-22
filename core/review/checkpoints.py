"""Content-addressed bundle checkpoints; final verification is always rerun."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.review.artifacts import write_json_atomic
from core.review.jobs import digest
from core.runtime.models import Candidate


def reviewer_identity() -> str:
    root = Path(__file__).resolve().parents[2]
    sources = sorted([*root.joinpath("core").rglob("*.py"), *root.joinpath("cli").rglob("*.py"), root/"config.py"])
    hasher = hashlib.sha256()
    for path in sources:
        hasher.update(str(path.relative_to(root)).replace("\\", "/").encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


class BundleCheckpoints:
    def __init__(self, root: Path, identity: dict):
        self.root, self.identity = root, identity

    def _path(self, bundle):
        return self.root/(digest({"identity": self.identity, "bundle": bundle.to_dict()})+".json")

    def load(self, bundle):
        path = self._path(bundle)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            value = envelope["value"]
            if envelope["sha256"] != digest(value) or value["record"]["status"] not in {"VALID_EMPTY", "VALID_CANDIDATES"}:
                return None
            candidates = [Candidate(**candidate) for candidate in value["candidates"]]
            if any(c.bundle_id != bundle.id or c.verify_status != "candidate" for c in candidates):
                return None
            return candidates, {**value["record"], "checkpoint_reused": True}
        except (ValueError, KeyError, TypeError, OSError):
            return None

    def save(self, bundle, candidates, record):
        if record.get("status") not in {"VALID_EMPTY", "VALID_CANDIDATES"}:
            return
        value = {"candidates": [c.to_dict() for c in candidates], "record": record}
        write_json_atomic(self._path(bundle), {"sha256": digest(value), "value": value})
