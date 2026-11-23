import base64
import hashlib

import httpx
import pytest

from benchmark.blind_pilot import PilotSource
from core.input.snapshot import InputError, ReviewSnapshot


def test_pilot_source_authenticates_blob_bytes_and_caches_shared_ancestors():
    raw = b"x = 1\n"
    oid = hashlib.sha1(b"blob 6\0" + raw).hexdigest()
    revision = "a" * 40
    tree = "b" * 40
    snapshot = ReviewSnapshot(repository_identity="a/b", head_sha=revision, base_sha="c"*40,
                              config_sha256="d"*64, diff_sha256=hashlib.sha256(b"").hexdigest())
    records = {revision: {"sha": revision, "tree": {"sha": tree}},
               tree: {"sha": tree, "tree": [
                   {"path":"app.py","sha":oid,"mode":"100644","type":"blob","size":len(raw)},
                   {"path":"test_app.py","sha":oid,"mode":"100644","type":"blob","size":len(raw)},
                   {"path":"link","sha":oid,"mode":"120000","type":"blob","size":len(raw)}]},
               oid: {"encoding":"base64","size":len(raw),"content":base64.b64encode(raw).decode()}}
    def respond(req):
        return httpx.Response(200, json=records[req.url.path.split("/")[-1]])
    with httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(respond)) as client:
        source = PilotSource(client, "a/b", snapshot, "")
        assert source.read(snapshot,"app.py").content == source.read(snapshot,"app.py").content == raw
        assert source.requests == 3
        assert source.paths(snapshot) == ()
        assert "test_app.py" in source.context_paths(snapshot)
        assert source.read(snapshot, "test_app.py").content == raw
        assert source.requests == 3
        with pytest.raises(InputError, match="regular files"):
            source.read(snapshot,"link")
        records[oid]["content"] = base64.b64encode(b"y = 1\n").decode()
        with pytest.raises(InputError, match="identity"):
            PilotSource(client, "a/b", snapshot, "").read(snapshot, "app.py")
