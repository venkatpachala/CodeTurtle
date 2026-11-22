import json
import os
from pathlib import Path

import pytest

from core.input.snapshot import GitSnapshotProvider, InputError
from core.review.isolated import DockerRunner, IsolationProfile, export_snapshot
from tests.test_input_snapshot import repository, git

IMAGE = "python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b"


def test_mutable_images_and_unbounded_profiles_are_rejected():
    with pytest.raises(ValueError): IsolationProfile(image="python:latest")
    with pytest.raises(ValueError): IsolationProfile(image=IMAGE, timeout_seconds=10000)
    with pytest.raises(ValueError): IsolationProfile(image=IMAGE, memory_mb=10000)


def test_export_uses_pinned_objects_and_rejects_budgets(repository, tmp_path):
    root, base = repository
    provider = GitSnapshotProvider(root); snapshot = provider.resolve(base)
    (root/"app.py").write_text("dirty = True")
    destination = tmp_path/"export"; destination.mkdir()
    exported = export_snapshot(provider, snapshot, destination)
    assert (destination/"app.py").read_text() == "limit = 2\n"
    assert not (destination/".git").exists() and exported["files"] == 1
    with pytest.raises(InputError, match="byte budget"):
        export_snapshot(provider, snapshot, destination, max_bytes=1)


def test_unavailable_docker_never_falls_back_to_host(repository):
    root, base = repository; provider = GitSnapshotProvider(root)
    result = DockerRunner(IsolationProfile(image=IMAGE), executable="unavailable-codeturtle-docker").run(
        provider, provider.resolve(base), ["python","-c","raise Exception('must not execute on host')"])
    assert result["status"] == "unavailable" and result["tests_executed"] is False


@pytest.fixture
def live_runner():
    executable = os.environ.get("CODETURTLE_TEST_DOCKER")
    if not executable:
        pytest.skip("live Docker qualification is explicitly enabled outside the default unit suite")
    staging = os.environ.get("CODETURTLE_TEST_STAGING")
    return lambda **kwargs: DockerRunner(IsolationProfile(image=IMAGE, **kwargs), executable=executable,
                                         staging_root=Path(staging) if staging else None)


def test_live_container_blocks_network_writes_credentials_and_privileges(repository, live_runner, monkeypatch):
    root, base = repository; provider = GitSnapshotProvider(root)
    monkeypatch.setenv("CODETURTLE_CANARY", "host-only-marker")
    probe = '''import os,socket,pathlib,json
def denied(path):
 try: pathlib.Path(path).write_text("escape"); return False
 except OSError: return True
s=socket.socket();s.settimeout(.3)
try: s.connect(("1.1.1.1",443)); network=False
except OSError: network=True
print(json.dumps(dict(nonroot=os.getuid()!=0,root_readonly=denied("/escape"),source_readonly=denied("/workspace/escape"),network_denied=network,no_host_secret=os.getenv("CODETURTLE_CANARY") is None,no_docker_socket=not pathlib.Path("/var/run/docker.sock").exists(),pinned_source=pathlib.Path("app.py").read_text()=="limit = 2\\n")))
'''
    result = live_runner().run(provider, provider.resolve(base), ["python","-c",probe])
    assert result["status"] == "passed", result
    assert all(json.loads(result["output"]).values()), result
    assert result["container_removed"]
    assert result["controls"]["NetworkMode"] == "none" and result["controls"]["ReadonlyRootfs"]
    assert result["controls"]["Memory"] == 512*1024*1024
    assert result["controls"]["PidsLimit"] == 64


def test_live_identical_probe_distinguishes_base_and_head(repository, live_runner):
    root, base = repository; provider = GitSnapshotProvider(root); snapshot = provider.resolve(base)
    runner = live_runner()
    command = ["python","-c","import app; assert app.limit == 1"]
    before = runner.run(provider, snapshot, command, side="base")
    after = runner.run(provider, snapshot, command, side="head")
    assert before["status"] == "passed" and after["status"] == "failed", (before,after)
    assert before["container_removed"] and after["container_removed"]


@pytest.mark.parametrize("mode", ["timeout", "output", "memory"])
def test_live_resource_limits_and_cleanup(repository, live_runner, mode):
    root, base = repository; provider = GitSnapshotProvider(root)
    command = {"timeout":"import time;time.sleep(60)","output":"print('x'*200000)","memory":"x=bytearray(256*1024*1024)"}[mode]
    result = live_runner(timeout_seconds=1 if mode=="timeout" else 15,
                         memory_mb=64 if mode=="memory" else 512).run(provider,provider.resolve(base),["python","-c",command])
    assert result["status"] == {"timeout":"timed_out","output":"output_limit","memory":"failed"}[mode], result
    assert result["container_removed"] and len(result["output"].encode()) <= 65536
    if mode == "memory": assert result["oom_killed"]
