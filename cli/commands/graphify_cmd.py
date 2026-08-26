from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from core.utils import handle_error
from core.repository_knowledge.factory import get_knowledge_provider
from core.repository_knowledge.graphify_mcp import GraphifyMCPError
from core.repository_knowledge.paths import resolve_graph_path

console = Console()


def graphify_test(
    repo: str = typer.Argument(
        ...,
        help="Repository in format owner/repo (e.g. FalkorDB/QueryWeaver)",
    ),
    query: str = typer.Option("", "--query", "-q", help="Natural language graph query"),
    node: str = typer.Option("", "--node", "-n", help="Lookup a node label"),
    path_from: str = typer.Option("", "--from", help="shortest_path source"),
    path_to: str = typer.Option("", "--to", help="shortest_path target"),
    stats: bool = typer.Option(False, "--stats", help="Show graph_stats"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Handshake Graphify MCP for a specific repository graph."""
    try:
        graph_path = resolve_graph_path(repo)
        provider = get_knowledge_provider(repo=repo)

        console.print(
            Panel.fit(
                f"[bold cyan]CodeTurtle × Graphify[/bold cyan]\n"
                f"Repo: {repo}\n"
                f"Graph: {graph_path}"
            )
        )

        tools = provider.list_tools()
        console.print(f"[green]Connected.[/green] Tools: {', '.join(tools) or '(none)'}")

        if stats or not (query or node or (path_from and path_to)):
            result = provider.graph_stats()
            console.print("\n[bold]graph_stats[/bold]")
            console.print(Markdown(result.raw_text or "_empty_"))

        if query:
            result = provider.query(query)
            console.print("\n[bold]query_graph[/bold]")
            console.print(Markdown(result.raw_text or "_empty_"))

        if node:
            found = provider.get_node(node)
            neighbors = provider.get_neighbors(node)
            console.print(f"\n[bold]get_node[/bold] {node}")
            text = (found.raw.get("text") if found else "_not found_") or "_empty_"
            console.print(Markdown(text))
            console.print("\n[bold]get_neighbors[/bold]")
            console.print(Markdown(neighbors.raw_text or "_empty_"))

        if path_from and path_to:
            path = provider.shortest_path(path_from, path_to)
            console.print(f"\n[bold]shortest_path[/bold] {path_from} → {path_to}")
            console.print(Markdown(path.raw_text or "_empty_"))

    except GraphifyMCPError as e:
        handle_error(e, verbose=verbose)
    except Exception as e:
        handle_error(e, verbose=verbose)