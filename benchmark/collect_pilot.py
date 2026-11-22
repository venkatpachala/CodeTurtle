"""Collect pinned public candidates without reading review comments as truth."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess

import httpx

from benchmark.pilot import PilotCase, register
from core.review.artifacts import write_json_atomic
from core.review.jobs import digest


def collect(pool: Path, output: Path, cache: Path):
    raw=json.loads(pool.read_text(encoding="utf-8"));cache.mkdir(parents=True,exist_ok=True)
    token=subprocess.check_output(["gh","auth","token","--hostname","github.com"],text=True,stderr=subprocess.PIPE).strip()
    headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
    client=httpx.Client(base_url="https://api.github.com",headers=headers,timeout=25,follow_redirects=True,
                        limits=httpx.Limits(max_connections=4))
    def get(path):
        response=client.get(path);response.raise_for_status();return response.json()
    candidates=[]
    for url,entry in raw.items():
        if entry.get("golden_comments"):
            candidates.append((url,entry.get("original_url") or url,"source_issue_candidate",
                               entry.get("source_repo") in {"discourse-graphite","sentry-greptile"}))
    for repo in ["fastapi/fastapi","encode/httpx","encode/starlette","pydantic/pydantic","fastapi/typer"]:
        merged=[p for p in get(f"/repos/{repo}/pulls?state=closed&per_page=30") if p.get("merged_at")]
        candidates.extend((p["html_url"],p["html_url"],"unreviewed_control",False) for p in merged[:8])
    failures=[];pinned=[];diffs={}
    def pin(item):
        url,origin,stratum,exposed=item
        pieces=url.split("/");repo="/".join(pieces[3:5]);number=pieces[-1]
        metadata=get(f"/repos/{repo}/pulls/{number}")
        if metadata["changed_files"]>100:
            raise ValueError("collection_file_limit")
        files=get(f"/repos/{repo}/pulls/{number}/files?per_page=100")
        if len(files)!=metadata["changed_files"]:
            raise ValueError("incomplete_file_inventory")
        code=[f for f in files if Path(f["filename"]).suffix in {".py",".rs",".ts",".js",".tsx",".java",".go",".rb"}]
        if not code or any(not f.get("patch") for f in code):
            raise ValueError("missing_code_patch_or_no_code")
        patch="\n".join(f"diff --git a/{f.get('previous_filename',f['filename'])} b/{f['filename']}\n--- a/{f.get('previous_filename',f['filename'])}\n+++ b/{f['filename']}\n{f.get('patch','')}\n" for f in files)
        if len(patch.encode())>1_000_000:
            raise ValueError("collection_patch_limit")
        base,head=metadata["base"]["sha"],metadata["head"]["sha"]
        comparison=get(f"/repos/{repo}/compare/{base}...{head}?per_page=1")["merge_base_commit"]["sha"]
        if get(f"/repos/{repo}/pulls/{number}")["head"]["sha"]!=head:
            raise ValueError("head_changed_during_collection")
        normalized=[(f["filename"],[line for line in f.get("patch","").splitlines() if line.startswith(("+","-"))]) for f in files]
        case=PilotCase(case_id="pr-"+digest(url)[:20],pr_url=url,original_url=origin,base_sha=base,head_sha=head,
                       comparison_base_sha=comparison,patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                       family_id=digest(sorted(normalized)),stratum=stratum,previously_exposed=exposed)
        return case,patch
    with ThreadPoolExecutor(max_workers=4) as workers:
        jobs={workers.submit(pin,item):item[0] for item in candidates}
        for future in as_completed(jobs):
            try:
                case,patch=future.result();pinned.append(case);diffs[case.case_id]=patch
            except Exception as error:
                failures.append({"pr_url":jobs[future],"error":type(error).__name__,
                                 "reason":str(error) if isinstance(error,ValueError) else "public metadata retrieval failed"})
            if (len(pinned)+len(failures))%10==0:
                print(f"candidate inputs pinned={len(pinned)} unavailable/ineligible={len(failures)}",flush=True)
    client.close()
    write_json_atomic(cache/"collection.json",{"source_pool_sha256":hashlib.sha256(pool.read_bytes()).hexdigest(),
        "candidate_count":len(candidates),"pinned":[c.model_dump(mode="json") for c in pinned],"failures":failures,
        "criteria":"At most 100 files / 1 MB patch, at least one supported code patch; source candidates plus first 8 merged PRs in closed listing per control repository. No model outcome selection."})
    manifest=register(pinned,output)
    patch_root=output/"patches";patch_root.mkdir()
    for case in json.loads((output/"inputs.json").read_text()):
        (patch_root/(case["case_id"]+".diff")).write_text(diffs[case["case_id"]],encoding="utf-8")
    write_json_atomic(output/"collection.json",json.loads((cache/"collection.json").read_text()))
    print(json.dumps(manifest),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--cache",type=Path,required=True);args=parser.parse_args()
    collect(args.pool,args.output,args.cache)
