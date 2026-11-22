"""Predict on a frozen PR split without loading annotations or GitHub review threads."""
from __future__ import annotations

import argparse
import base64
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import httpx

from benchmark.pilot import load_inputs, seal
from benchmark.release_manifest import freeze
from core.agent.bundle_agent import PROMPT_VERSION
from core.input.snapshot import GitSnapshotProvider, InputError, ReviewSnapshot, SourceNotFound, SourceRead
from core.review.artifacts import write_json_atomic
from core.review.budget import ReviewBudget
from core.review.contract import ReviewHealth, ReviewTarget
from core.review.jobs import digest
from core.runtime.models import ReviewResult
from core.runtime.review_runtime import ReviewRuntime
from core.verification.diff_index import build_diff_index


class PilotSource:
    """Frozen patch and regular source blobs resolved through exact Git commits and trees."""

    def __init__(self, client, repository, snapshot, patch):
        self.snapshot = snapshot
        self.patch = patch
        self.paths_changed = sorted(build_diff_index(patch).files)
        self.client = client
        self.prefix = f"/repos/{repository}/git"
        self.requests = 0
        self.tree = lru_cache(maxsize=256)(self._tree)
        self.commit_tree = lru_cache(maxsize=2)(self._commit_tree)
        self.read_blob = lru_cache(maxsize=24)(self._blob)

    def _get(self, path):
        self.requests += 1
        if self.requests > 240:
            raise InputError("source request limit")
        try:
            response = self.client.get(self.prefix + path)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InputError("pinned Git object unavailable") from exc

    def _tree(self, sha):
        tree = self._get(f"/trees/{sha}")
        if tree["sha"] != sha or tree.get("truncated"):
            raise InputError("tree identity or inventory incomplete")
        return {entry["path"]: entry for entry in tree["tree"]}

    def _commit_tree(self, sha):
        commit = self._get(f"/commits/{sha}")
        if commit["sha"] != sha:
            raise InputError("commit identity mismatch")
        return commit["tree"]["sha"]

    def _blob(self, sha, size):
        if size > 1_000_000:
            raise InputError("source byte limit")
        obj = self._get(f"/blobs/{sha}")
        if obj.get("encoding") != "base64" or obj.get("size") != size:
            raise InputError("unsupported source blob")
        raw = base64.b64decode("".join(obj["content"].split()), validate=True)
        oid = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        if oid != sha or len(raw) != size:
            raise InputError("source blob identity mismatch")
        return raw

    def diff(self, snapshot):
        if snapshot != self.snapshot or hashlib.sha256(self.patch.encode()).hexdigest() != snapshot.diff_sha256:
            raise InputError("frozen patch identity mismatch")
        return self.patch

    def paths(self, snapshot, side="head"):
        if snapshot != self.snapshot:
            raise InputError("foreign snapshot")
        return tuple(self.paths_changed)

    def read(self, snapshot, path, side="head"):
        if snapshot != self.snapshot:
            raise InputError("foreign snapshot")
        parts = GitSnapshotProvider._path(path).split("/")
        revision = snapshot.revision(side)
        tree_sha = self.commit_tree(revision)
        for i, part in enumerate(parts):
            entry = self.tree(tree_sha).get(part)
            if entry is None:
                raise SourceNotFound("path absent at revision")
            if i < len(parts) - 1:
                if entry["type"] != "tree":
                    raise InputError("non-directory component")
                tree_sha = entry["sha"]
        if entry["mode"] not in {"100644", "100755"} or entry["type"] != "blob":
            raise InputError("regular files only")
        raw = self.read_blob(entry["sha"], entry["size"])
        return SourceRead(snapshot_id=snapshot.id, revision_sha=revision, side=side, path=path,
                          content=raw, content_sha256=hashlib.sha256(raw).hexdigest())


def predict(root: Path, output: Path, split: str) -> None:
    registry, rows = load_inputs(root)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "predictions.json").exists():
        raise FileExistsError("predictions already sealed")
    # Re-check the live model identity even when resuming a partially completed run.
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        release = freeze(Path(directory) / "release.json")
    profile = {"release": release, "bundle_max": 1, "agent_max_steps": 2, "split": split,
               "inputs_sha256": registry["inputs_sha256"], "source_scope": "frozen patch; changed-path inventory; exact Git blobs on demand"}
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_bytes()) != profile:
        raise ValueError("resume requires identical frozen profile")
    write_json_atomic(manifest_path, profile)
    token = subprocess.check_output(["gh", "auth", "token", "--hostname", "github.com"], text=True).strip()
    results = []
    selected = [case for case in rows if case["split"] == split]
    with httpx.Client(base_url="https://api.github.com", headers={"Authorization": "Bearer " + token},
                      follow_redirects=True, timeout=12) as client:
        for case in selected:
            saved = output / (case["case_id"] + ".json")
            if saved.exists():
                row = json.loads(saved.read_bytes())
                if row["profile_sha256"] != digest(profile) or row["pr_url"] != case["pr_url"]:
                    raise ValueError("checkpoint profile or target mismatch")
                results.append(row)
                continue
            repo = "/".join(case["pr_url"].split("/")[3:5])
            number = int(case["pr_url"].split("/")[-1])
            target = {key: case[key] for key in ("base_sha", "head_sha", "comparison_base_sha")}
            snapshot = ReviewSnapshot(repository_identity=repo, diff_sha256=case["patch_sha256"],
                                      config_sha256=digest(profile), **target)
            patch = (root / "patches" / (case["case_id"] + ".diff")).read_bytes().decode()
            source = PilotSource(client, repo, snapshot, patch)
            started = time.monotonic()
            model = release["model_profile"]
            context = SimpleNamespace(repo=repo, number=number, full_diff=patch, files_changed=source.paths_changed,
                pr_base_sha=case["base_sha"], pr_head_sha=case["head_sha"], review_snapshot=snapshot,
                input_provider=source, requirement_strategy="off",
                repo_cfg=SimpleNamespace(bundle_max=profile["bundle_max"], agent_max_steps=profile["agent_max_steps"]))
            try:
                result = ReviewRuntime().run(context)
            except (RuntimeError, ValueError, OSError, httpx.HTTPError) as exc:
                result = ReviewResult(health=ReviewHealth(status="failed"), decision=None,
                    target=ReviewTarget(repo=repo, number=number, diff_sha256=case["patch_sha256"], **target),
                    provenance={"reviewer_commit":release["reviewer_commit"], "dirty":False, "model":model["model"],
                        "provider":model["provider"], "prompt_version":PROMPT_VERSION, "discovery_protocol":"semantic",
                        "requirement_strategy":"off", "finding_verifier_mode":"structured", "finding_source_rules":True,
                        "budget":{k:v for k,v in ReviewBudget().to_dict().items() if k.startswith("max_")},
                        "operational_error":type(exc).__name__})
            result.provenance.update(analysis_mode="model", pilot_profile=digest(profile), pilot_source=profile["source_scope"])
            row = {"pr_url":case["pr_url"], "profile_sha256":digest(profile), "source_requests":source.requests,
                   "elapsed_seconds":time.monotonic()-started, "result":result.to_dict()}
            write_json_atomic(saved, row)
            results.append(row)
            print(f"Pilot attempts recorded {len(results)}/{len(selected)}", flush=True)
    with tempfile.TemporaryDirectory() as directory:
        if freeze(Path(directory) / "after.json") != release:
            raise ValueError("release identity changed during prediction")
    seal(root, results, output / "predictions.json", split=split)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=["development","validation","test"], required=True)
    args = parser.parse_args()
    predict(args.root, args.output, args.split)
