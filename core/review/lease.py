"""OS-backed repository lease; a crashed process releases the lock automatically."""
from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def repository_lease(repo: str, root: Path, *, timeout: float = 30.0):
    directory = root / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(repo.lower().encode()).hexdigest() + ".lock"
    with (directory / name).open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + timeout
        acquired = False
        try:
            while not acquired:
                stream.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("repository is being reviewed by another process")
                    time.sleep(0.1)
            yield
        finally:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
