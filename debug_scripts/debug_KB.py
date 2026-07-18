import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.knowledge_base import KnowledgeBase

console = Console()


def verify_knowledge_base(repo_name: str, sample_size: int = 5):
    """Detailed inspection of what is stored in Qdrant."""

    collection_name = repo_name.replace("/", "_")
    model_path = Path(".codeturtle/repositories") / repo_name.replace("/", "_") / "repository_model.json"

    console.print(Panel.fit(
        f"[bold cyan]Qdrant Knowledge Base Inspection[/bold cyan]\n\n{repo_name}",
        title="CodeTurtle"
    ))

    if not model_path.exists():
        console.print("[red]repository_model.json not found.[/red]")
        return False

    kb = KnowledgeBase(collection_name)

    try:
        # Collection stats
        collection_info = kb.client.get_collection(collection_name)
        points_count = collection_info.points_count

        print(f"Collection: {collection_name}")
        print(f"Total vectors stored: {points_count}")

        # Sample documents
        print(f"\n[bold yellow]Sample {sample_size} documents from Qdrant:[/bold yellow]\n")

        # Scroll to get sample points
        scroll_result = kb.client.scroll(
            collection_name=collection_name,
            limit=sample_size,
            with_payload=True,
            with_vectors=False
        )

        for i, point in enumerate(scroll_result[0]):
            payload = point.payload
            print(f"--- Document {i+1} (ID: {point.id}) ---")
            print(f"Path: {payload.get('path', 'N/A')}")
            print(f"Language: {payload.get('language', 'N/A')}")
            print(f"Chunk Type: {payload.get('chunk_type', 'N/A')}")
            print(f"Lines: {payload.get('start_line')} - {payload.get('end_line')}")
            print(f"Symbols: {payload.get('symbols', [])}")
            print(f"Content preview:\n{payload.get('page_content', '')[:500]}...\n")

        # Summary statistics
        table = Table(title="Qdrant Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total points", str(points_count))
        table.add_row("Sampled documents", str(len(scroll_result[0])))
        table.add_row("Collection status", "Healthy" if points_count > 0 else "Empty")

        console.print(table)

        if points_count > 0:
            console.print("[green]✓ Qdrant knowledge base contains data.[/green]")
        else:
            console.print("[red]Qdrant collection is empty.[/red]")

    except Exception as e:
        console.print(f"[red]Qdrant inspection failed: {e}[/red]")


if __name__ == "__main__":
    verify_knowledge_base("NousResearch/hermes-agent")