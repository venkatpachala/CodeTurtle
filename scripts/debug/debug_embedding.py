import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.repository_model import RepositoryModel
from core.chunker import PythonChunker
from core.document_builder import DocumentBuilder
from langchain_ollama import OllamaEmbeddings

console = Console()


def verify_embedding(repo_name: str):
    """Verify document embedding stage."""

    model_path = Path(".codeturtle/repositories") / repo_name.replace("/", "_") / "repository_model.json"

    console.print(Panel.fit(
        f"[bold cyan]Embedding Verification[/bold cyan]\n\n{repo_name}",
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
    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    total_documents = 0
    total_embeddings = 0
    failures = 0

    for fm in repository_model.files:
        if fm.language.lower() != "python":
            continue

        chunks = python_chunker.chunk(fm)

        for chunk in chunks:
            total_documents += 1

            try:
                doc = document_builder.build(chunk)
                embedding = embeddings.embed_query(doc.page_content)
                total_embeddings += 1

                if len(embedding) != 768:
                    failures += 1
                    console.print(f"[red]Wrong dimension for {chunk.path} chunk {chunk.chunk_index}[/red]")

            except Exception as e:
                failures += 1
                console.print(f"[red]Embedding failed for {chunk.path} chunk {chunk.chunk_index}: {e}[/red]")

    # Summary
    table = Table(title="Embedding Verification Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Documents created", str(total_documents))
    table.add_row("Embeddings generated", str(total_embeddings))
    table.add_row("Failures", str(failures))

    console.print(table)

    if failures == 0:
        console.print("[green]✓ Embedding stage passed: all documents embedded successfully with correct dimensions.[/green]")
    else:
        console.print("[red]Embedding stage has failures.[/red]")

    return failures == 0


if __name__ == "__main__":
    verify_embedding("NousResearch/hermes-agent")