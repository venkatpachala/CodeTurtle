"""Durable local review commands; they never post GitHub reviews or run PR code."""
import json
from pathlib import Path

import typer

from core.input.snapshot import GitSnapshotProvider
from core.review.checkpoints import reviewer_identity
from core.review.jobs import JobStore
from core.review.worker import review_config, work_once
from core.user_config import home_dir

app = typer.Typer(help="Durable local review queue, recovery, cancellation and finding feedback")


def store(db):
    return JobStore(db or home_dir()/"jobs"/"reviews.sqlite3")


@app.command()
def submit(repo: Path = typer.Option(..., exists=True, file_okay=False), base: str = typer.Option(...),
           head: str = "HEAD", static_only: bool = False, bundle_max: int = typer.Option(12, min=1, max=32),
           timeout_seconds: int = typer.Option(600, min=1, max=3600),
           requirements: Path | None = typer.Option(None, exists=True, dir_okay=False),
           previous: Path | None = typer.Option(None, exists=True, dir_okay=False),
           idempotency_key: str | None = None, db: Path | None = None):
    provider = GitSnapshotProvider(repo)
    snapshot = provider.resolve(base, head)
    payload = {"repo": provider.identity, "base_sha": snapshot.base_sha, "head_sha": snapshot.head_sha,
               "diff_sha256": snapshot.diff_sha256, "reviewer": reviewer_identity(), "review_config": review_config(),
               "static_only": static_only, "bundle_max": bundle_max, "timeout_seconds": timeout_seconds,
               "requirements": requirements.read_text(encoding="utf-8") if requirements else None,
               "previous": previous.read_text(encoding="utf-8") if previous else None}
    job = store(db).submit(payload, key=idempotency_key)
    typer.echo(json.dumps({"id": job["id"], "state": job["state"], "head_sha": snapshot.head_sha}))


@app.command()
def work(db: Path | None = None, max_jobs: int = typer.Option(1, min=1, max=100)):
    queue = store(db)
    for _ in range(max_jobs):
        job = work_once(queue)
        if job is None:
            break
        typer.echo(json.dumps({"id": job["id"], "state": job["state"], "artifact": job["artifact"], "error": job["error"]}))


@app.command()
def show(job_id: str, db: Path | None = None):
    queue = store(db)
    typer.echo(json.dumps({"job": queue.get(job_id), "events": queue.events(job_id)}, indent=2))


@app.command()
def cancel(job_id: str, db: Path | None = None):
    typer.echo(json.dumps({"state": store(db).cancel(job_id)["state"]}))


@app.command()
def retry(job_id: str, db: Path | None = None):
    typer.echo(json.dumps({"state": store(db).retry(job_id)["state"]}))


@app.command()
def findings(repo: Path = typer.Option(..., exists=True), db: Path | None = None):
    typer.echo(json.dumps(store(db).findings(GitSnapshotProvider(repo).identity), indent=2))


@app.command()
def feedback(fingerprint: str, repo: Path = typer.Option(..., exists=True), state: str = typer.Option(...),
             actor: str = typer.Option(...), evidence: str = typer.Option(...), db: Path | None = None):
    store(db).finding_state(GitSnapshotProvider(repo).identity, fingerprint, state, actor=actor, evidence=evidence)
    typer.echo("Finding feedback recorded")
