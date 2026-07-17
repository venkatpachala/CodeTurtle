import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.knowledge_base import KnowledgeBase
from core.repository_model import RepositoryModel

console = Console()


def verify_qdrant(repo_name: str):
    """Verify Qdrant storage after embedding."""

    collection_name = repo_name.replace("/", "_")
    model_path = Path(".codeturtle/repositories") / repo_name.replace("/", "_") / "repository_model.json"

    console.print(Panel.fit(
        f"[bold cyan]Qdrant Verification[/bold cyan]\n\n{repo_name}",
        title="CodeTurtle"
    ))

    if not model_path.exists():
        console.print("[red]repository_model.json not found.[/red]")
        return False

    # Load model for expected count
    with open(model_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    expected_documents = len(data.get("files", []))

    # Qdrant check
    kb = KnowledgeBase(collection_name)

    try:
        points_count = kb.client.get_collection(collection_name).points_count
        print(f"Points in Qdrant: {points_count}")

        table = Table(title="Qdrant Verification Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Expected documents", str(expected_documents))
        table.add_row("Stored vectors", str(points_count))
        table.add_row("Collection name", collection_name)

        console.print(table)

        if points_count > 0 and points_count >= expected_documents * 0.8:  # allow some variation
            console.print("[green]✓ Qdrant storage looks healthy.[/green]")
        else:
            console.print("[red]Qdrant has significantly fewer vectors than expected.[/red]")

    except Exception as e:
        console.print(f"[red]Qdrant verification failed: {e}[/red]")


if __name__ == "__main__":
    verify_qdrant("NousResearch/hermes-agent")