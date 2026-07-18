import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.repository_model import RepositoryModel
from core.chunker import PythonChunker
from core.document_builder import DocumentBuilder

console = Console()


def verify_document_builder(repo_name: str):
    """Verify DocumentBuilder produces correct rich documents."""

    repo_path = Path("repos") / repo_name.replace("/", "_")
    model_path = Path(".codeturtle/repositories") / repo_name.replace("/", "_") / "repository_model.json"

    console.print(Panel.fit(
        f"[bold cyan]DocumentBuilder Verification[/bold cyan]\n\n{repo_name}",
        title="CodeTurtle"
    ))

    if not model_path.exists():
        console.print("[red]repository_model.json not found.[/red]")
        return False

    with open(model_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    repository_model = RepositoryModel.model_validate(data)

    python_chunker = PythonChunker()
    document_builder = DocumentBuilder()

    total_documents = 0
    problems = []

    for fm in repository_model.files:
        if fm.language.lower() != "python":
            continue

        chunks = python_chunker.chunk(fm)

        for chunk in chunks:
            doc = document_builder.build(chunk)
            total_documents += 1

            # Check metadata
            metadata = doc.metadata

            if metadata.get("path") != chunk.path:
                problems.append(f"{chunk.path} chunk {chunk.chunk_index}: wrong path")

            if metadata.get("language") != chunk.language:
                problems.append(f"{chunk.path} chunk {chunk.chunk_index}: wrong language")

            if metadata.get("start_line") != chunk.start_line:
                problems.append(f"{chunk.path} chunk {chunk.chunk_index}: wrong start_line")

            if metadata.get("end_line") != chunk.end_line:
                problems.append(f"{chunk.path} chunk {chunk.chunk_index}: wrong end_line")

            if metadata.get("chunk_type") != chunk.chunk_type:
                problems.append(f"{chunk.path} chunk {chunk.chunk_index}: wrong chunk_type")

            if metadata.get("symbols") != (chunk.symbols or []):
                problems.append(f"{chunk.path} chunk {chunk.chunk_index}: symbols mismatch")

            # Check content contains key parts
            if chunk.path not in doc.page_content:
                problems.append(f"{chunk.path} chunk {chunk.chunk_index}: path not in content")

            if chunk.code not in doc.page_content:
                problems.append(f"{chunk.path} chunk {chunk.chunk_index}: code not in content")

    # Summary
    table = Table(title="DocumentBuilder Verification Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Documents created", str(total_documents))
    table.add_row("Problems found", str(len(problems)) if problems else "0")

    console.print(table)

    if problems:
        console.print("[red]Problems detected:[/red]")
        for p in problems[:10]:
            console.print(f"  - {p}")
        if len(problems) > 10:
            console.print(f"  ... and {len(problems)-10} more")
    else:
        console.print("[green]✓ DocumentBuilder passed all checks: metadata correct, content rich, code preserved.[/green]")

    return len(problems) == 0


if __name__ == "__main__":
    verify_document_builder("NousResearch/hermes-agent")