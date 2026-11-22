"""Single-machine durable review queue with leases, fencing and audit events."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


def encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class LostLease(RuntimeError):
    pass


class JobStore:
    def __init__(self, path: Path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                  state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                  cancelled INTEGER NOT NULL DEFAULT 0, token TEXT, lease REAL,
                  created REAL NOT NULL, updated REAL NOT NULL, artifact TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS job_events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                  at REAL NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tracked_findings (
                  project TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                  first_job TEXT NOT NULL, last_job TEXT NOT NULL, body TEXT NOT NULL,
                  PRIMARY KEY(project,fingerprint));
                CREATE TABLE IF NOT EXISTS finding_events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL,
                  fingerprint TEXT NOT NULL, at REAL NOT NULL, state TEXT NOT NULL,
                  actor TEXT NOT NULL, evidence TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _event(self, db, job_id, event, detail=None):
        db.execute("INSERT INTO job_events(job_id,at,event,detail) VALUES(?,?,?,?)",
                   (job_id, self.clock(), event, encoded(detail or {})))

    @staticmethod
    def _record(row):
        if row is None:
            raise KeyError("unknown job")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def get(self, job_id: str) -> dict:
        with self.connection() as db:
            return self._record(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def submit(self, payload: dict, *, key: str | None = None) -> dict:
        content = encoded(payload)
        key = key or digest(payload)
        with self.transaction() as db:
            old = db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            if old:
                if old["payload"] != content:
                    raise ValueError("idempotency key already identifies a different immutable request")
                return self._record(old)
            job_id, now = uuid.uuid4().hex, self.clock()
            db.execute("INSERT INTO jobs(id,key,payload,state,created,updated) VALUES(?,?,?,'queued',?,?)",
                       (job_id, key, content, now, now))
            self._event(db, job_id, "submitted")
        return self.get(job_id)

    def claim(self, *, lease_seconds=30, max_attempts=3) -> dict | None:
        if lease_seconds <= 0 or max_attempts < 1:
            raise ValueError("invalid worker limits")
        with self.transaction() as db:
            now = self.clock()
            for row in db.execute("SELECT * FROM jobs WHERE state='running' AND lease<=?", (now,)).fetchall():
                state = "cancelled" if row["cancelled"] else "failed" if row["attempt"] >= max_attempts else "queued"
                db.execute("UPDATE jobs SET state=?,token=NULL,lease=NULL,updated=?,error=? WHERE id=?",
                           (state, now, "lease_expired", row["id"]))
                self._event(db, row["id"], "lease_expired", {"next_state": state})
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',attempt=attempt+1,token=?,lease=?,updated=?,error=NULL WHERE id=?",
                       (token, now+lease_seconds, now, row["id"]))
            self._event(db, row["id"], "claimed", {"attempt": row["attempt"]+1})
            return self._record(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def _owned(self, db, job_id, token):
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or row["state"] != "running" or row["token"] != token or row["lease"] <= self.clock():
            raise LostLease("worker no longer owns this attempt")
        return row

    def heartbeat(self, job_id: str, token: str, *, lease_seconds=30) -> bool:
        with self.transaction() as db:
            row = self._owned(db, job_id, token)
            db.execute("UPDATE jobs SET lease=?,updated=? WHERE id=?", (self.clock()+lease_seconds, self.clock(), job_id))
            return bool(row["cancelled"])

    def cancel(self, job_id: str) -> dict:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError("unknown job")
            if row["state"] in {"queued", "running"}:
                state = "cancelled" if row["state"] == "queued" else "running"
                db.execute("UPDATE jobs SET cancelled=1,state=?,updated=? WHERE id=?", (state, self.clock(), job_id))
                self._event(db, job_id, "cancellation_requested")
        return self.get(job_id)

    def finish(self, job_id: str, token: str, *, artifact: str = "", report: dict | None = None,
               error: str = "") -> dict:
        with self.transaction() as db:
            row = self._owned(db, job_id, token)
            state = "cancelled" if row["cancelled"] else "failed" if error else "succeeded"
            if report is not None and state == "succeeded":
                payload = json.loads(row["payload"])
                if any(report["target"].get(k) != payload[k] for k in ("base_sha", "head_sha")):
                    raise ValueError("worker artifact differs from immutable task target")
                self._observe_findings(db, payload["repo"], job_id, report.get("product_findings", []))
            db.execute("UPDATE jobs SET state=?,artifact=?,error=?,lease=NULL,token=NULL,updated=? WHERE id=?",
                       (state, artifact, error, self.clock(), job_id))
            self._event(db, job_id, state, {"artifact": artifact, "error": error})
        return self.get(job_id)

    def events(self, job_id: str) -> list[dict]:
        with self.connection() as db:
            return [dict(row) | {"detail": json.loads(row["detail"])} for row in
                    db.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY seq", (job_id,))]

    def retry(self, job_id: str) -> dict:
        with self.transaction() as db:
            row = db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] not in {"failed", "cancelled"}:
                raise ValueError("only failed or cancelled jobs can be explicitly retried")
            db.execute("UPDATE jobs SET state='queued',cancelled=0,error=NULL,updated=? WHERE id=?", (self.clock(), job_id))
            self._event(db, job_id, "explicit_retry")
        return self.get(job_id)

    def _observe_findings(self, db, project, job_id, findings):
        seen = set()
        for finding in findings:
            identity = {key: finding.get(key) for key in ("file", "invariant", "violating_condition", "expected", "actual")}
            fingerprint = digest(identity)
            seen.add(fingerprint)
            db.execute("INSERT INTO tracked_findings VALUES(?,?,'open',?,?,?) ON CONFLICT(project,fingerprint) "
                       "DO UPDATE SET state='open',last_job=excluded.last_job,body=excluded.body",
                       (project, fingerprint, job_id, job_id, encoded(finding)))
            db.execute("INSERT INTO finding_events(project,fingerprint,at,state,actor,evidence) VALUES(?,?,?,'open','review',?)",
                       (project, fingerprint, self.clock(), job_id))
        for row in db.execute("SELECT fingerprint FROM tracked_findings WHERE project=? AND state='open'", (project,)).fetchall():
            if row["fingerprint"] not in seen:
                # Absence of a finding is not evidence that its defect was fixed.
                db.execute("UPDATE tracked_findings SET state='needs_recheck' WHERE project=? AND fingerprint=?",
                           (project, row["fingerprint"]))

    def findings(self, project: str) -> list[dict]:
        with self.connection() as db:
            return [dict(r) | {"body": json.loads(r["body"])} for r in
                    db.execute("SELECT * FROM tracked_findings WHERE project=?", (project,))]

    def finding_state(self, project: str, fingerprint: str, state: str, *, actor: str, evidence: str):
        if state not in {"open", "resolved", "false_positive"} or not actor.strip() or not evidence.strip():
            raise ValueError("finding feedback requires state, actor and audit evidence")
        with self.transaction() as db:
            if db.execute("UPDATE tracked_findings SET state=? WHERE project=? AND fingerprint=?",
                          (state, project, fingerprint)).rowcount != 1:
                raise KeyError("unknown tracked finding")
            db.execute("INSERT INTO finding_events(project,fingerprint,at,state,actor,evidence) VALUES(?,?,?,?,?,?)",
                       (project, fingerprint, self.clock(), state, actor, evidence))
