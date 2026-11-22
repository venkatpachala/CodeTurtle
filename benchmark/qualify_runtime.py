"""Repeatable live qualification of the local Docker execution profile."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

from benchmark.requirement_experiment import _git
from core.input.snapshot import GitSnapshotProvider
from core.review.artifacts import write_json_atomic
from core.review.isolated import DockerRunner, IsolationProfile

SAFETY_PROBE='''import json,os,socket,pathlib
def denied(path):
 try: pathlib.Path(path).write_text("escape"); return False
 except OSError: return True
s=socket.socket();s.settimeout(.3)
try: s.connect(("1.1.1.1",443)); network=False
except OSError: network=True
print(json.dumps(dict(nonroot=os.getuid()!=0,root_readonly=denied("/escape"),source_readonly=denied("/workspace/escape"),network_denied=network,no_host_secret=os.getenv("CODETURTLE_QUALIFICATION_CANARY") is None,no_docker_socket=not pathlib.Path("/var/run/docker.sock").exists())))
'''


def qualify(image: str, executable: str, staging_root: Path | None, output: Path) -> dict:
    runs={};old=os.environ.get("CODETURTLE_QUALIFICATION_CANARY")
    os.environ["CODETURTLE_QUALIFICATION_CANARY"]="host-only-qualification-marker"
    try:
        with tempfile.TemporaryDirectory(prefix="ct-qualification-") as directory:
            root=Path(directory);_git(root,"init");_git(root,"config","user.name","Runtime fixture")
            _git(root,"config","user.email","fixture@example.invalid")
            (root/"app.py").write_text("VALUE = 1\n");_git(root,"add",".");_git(root,"commit","-m","base")
            base=_git(root,"rev-parse","HEAD")
            (root/"app.py").write_text("VALUE = 2\n");_git(root,"commit","-am","head")
            provider=GitSnapshotProvider(root);snapshot=provider.resolve(base)
            def run(name,code,side="head",**limits):
                runner=DockerRunner(IsolationProfile(image=image,**limits),executable=executable,staging_root=staging_root)
                runs[name]=runner.run(provider,snapshot,["python","-c",code],side=side)
            run("safety",SAFETY_PROBE)
            run("base_probe","import app;assert app.VALUE == 1",side="base")
            run("head_probe","import app;assert app.VALUE == 1")
            run("timeout","import time;time.sleep(60)",timeout_seconds=1)
            run("output_limit","print('x'*200000)")
            run("memory_limit","x=bytearray(256*1024*1024)",memory_mb=64)
    finally:
        if old is None: os.environ.pop("CODETURTLE_QUALIFICATION_CANARY",None)
        else: os.environ["CODETURTLE_QUALIFICATION_CANARY"]=old
    try:
        safety=json.loads(runs["safety"]["output"])
    except (ValueError,KeyError): safety={}
    checks={"all_safety_properties":len(safety)==6 and all(safety.values()),
            "base_passes":runs["base_probe"]["status"]=="passed", "head_fails":runs["head_probe"]["status"]=="failed",
            "deadline":runs["timeout"]["status"]=="timed_out", "output_limit":runs["output_limit"]["status"]=="output_limit",
            "oom_limit":runs["memory_limit"].get("oom_killed") is True,
            "all_containers_removed":all(r.get("container_removed") is True for r in runs.values()),
            "all_probes_executed":all(r["tests_executed"] for r in runs.values())}
    for run in runs.values():
        text=run["output"];run.update(output_sha256=hashlib.sha256(text.encode()).hexdigest(),captured_output_bytes=len(text.encode()))
        run["output"]=text[:512]
    report={"passed":all(checks.values()),"checks":checks,"runs":runs,"safety_properties":safety,
            "scope":"Controlled Python/Docker local profile qualification, not arbitrary-language build validation or a microVM security audit.",
            "resource_measurement":"Limits and OOM enforcement measured; peak host/model resource consumption and monetary cost are not measured."}
    write_json_atomic(output,report)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image",required=True);parser.add_argument("--docker",default=os.environ.get("CODETURTLE_DOCKER","docker"))
    parser.add_argument("--staging-root",type=Path);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();result=qualify(args.image,args.docker,args.staging_root,args.output)
    print(json.dumps({"passed":result["passed"],"checks":result["checks"]}))
    raise SystemExit(0 if result["passed"] else 1)
