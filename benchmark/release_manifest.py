"""Freeze reproducibility metadata; this manifest does not certify review quality."""
import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import subprocess

import httpx

from core.review.artifacts import write_json_atomic
from core.review.checkpoints import reviewer_identity
from core.review.worker import review_config


def freeze(output: Path):
    if output.exists(): raise FileExistsError("release metadata cannot overwrite an existing freeze")
    root=Path(__file__).resolve().parents[1]
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
    if subprocess.check_output(["git","status","--porcelain"],cwd=root,text=True).strip():
        raise ValueError("freeze requires a clean reviewer checkout")
    packages={}
    for name in ["pydantic","httpx","langchain-ollama","PyGithub","typer"]:
        try: packages[name]=version(name)
        except PackageNotFoundError: packages[name]=None
    profile=review_config();model_digest=None
    if profile["provider"]=="ollama":
        from config import settings
        response=httpx.get(settings.ollama_base_url.rstrip("/")+"/api/tags",timeout=10);response.raise_for_status()
        model=next((m for m in response.json().get("models",[]) if m.get("name")==profile["model"]),None)
        if model is None: raise ValueError("selected local model is unavailable")
        model_digest=model.get("digest")
    scorer=root/"benchmark/metrics.py"
    manifest={"reviewer_commit":commit,"reviewer_identity":reviewer_identity(),"reviewer_dirty":False,
        "python":platform.python_version(),"platform":platform.platform(),"cpu_count":os.cpu_count(),"packages":packages,
        "model_profile":profile,"observed_model_digest":model_digest,
        "scorer_sha256":hashlib.sha256(scorer.read_bytes()).hexdigest(),
        "quality_qualified":False,"limitations":["Model digest observed at freeze time; verify it again after trials.",
            "This is reproducibility metadata, not a benchmark result or release qualification.",
            "GPU/peak memory, electricity and monetary inference cost are not established by this manifest."]}
    write_json_atomic(output,manifest)
    return manifest


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();record=freeze(args.output);print(record["reviewer_commit"])
