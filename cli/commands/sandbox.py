"""Explicit isolated execution; default review commands never execute PR code."""
import os
from pathlib import Path
import typer

from core.input.snapshot import GitSnapshotProvider
from core.review.artifacts import write_json_atomic
from core.review.isolated import DockerRunner, IsolationProfile


def sandbox_check(command: list[str] = typer.Argument(...), repo: Path = typer.Option(..., exists=True, file_okay=False),
                  base: str = typer.Option(...), head: str = "HEAD", image: str = typer.Option(...),
                  timeout_seconds: float = typer.Option(30, min=1, max=600),
                  staging_root: Path | None = None, json_output: Path = Path("sandbox-result.json")):
    provider = GitSnapshotProvider(repo)
    snapshot = provider.resolve(base, head)
    runner = DockerRunner(IsolationProfile(image=image, timeout_seconds=timeout_seconds),
                          executable=os.environ.get("CODETURTLE_DOCKER", "docker"), staging_root=staging_root)
    reports = [runner.run(provider, snapshot, command, side=side) for side in ("base", "head")]
    write_json_atomic(json_output, {"snapshot": snapshot.model_dump(mode="json"), "runs": reports,
                                  "interpretation": "Identical command, separately exported revisions. Outcomes alone do not prove an introduced defect."})
    typer.echo(f"BASE={reports[0]['status']} HEAD={reports[1]['status']}; report={json_output}")
    if any(r["status"] != "passed" for r in reports):
        raise typer.Exit(1)
