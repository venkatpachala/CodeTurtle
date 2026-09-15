from github import Github
from core.hybrid_retriever import HybridRetriever
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


def debug_retriever(repo_name: str, query: str, k: int = 8):
    """Debug what the HybridRetriever returns for a given query."""

    console.print(Panel.fit(
        f"[bold cyan]Retriever Debug[/bold cyan]\n\n{repo_name}",
        title="CodeTurtle"
    ))

    print(f"Query: {query}\n")

    retriever = HybridRetriever(repo_name)
    retrieved_docs = retriever.retrieve(query, k=k)

    print(f"[bold yellow]Retrieved {len(retrieved_docs)} documents[/bold yellow]\n")

    for i, doc in enumerate(retrieved_docs):
        print(f"--- Document {i+1} ---")
        print(f"Path: {doc.metadata.get('path', 'N/A')}")
        print(f"Chunk Type: {doc.metadata.get('chunk_type', 'N/A')}")
        print(f"Lines: {doc.metadata.get('start_line')} - {doc.metadata.get('end_line')}")
        print(f"Symbols: {doc.metadata.get('symbols', [])}")
        print(f"Relevance Preview:\n{doc.page_content[:600]}...\n")

    # Save for later analysis
    with open(f"debug_retriever_{repo_name.replace('/', '_')}.txt", "w", encoding="utf-8") as f:
        f.write(f"Query: {query}\n\n")
        for i, doc in enumerate(retrieved_docs):
            f.write(f"Document {i+1}\n")
            f.write(f"Path: {doc.metadata.get('path')}\n")
            f.write(f"Content:\n{doc.page_content}\n\n")

    print("[green]Debug output saved.[/green]")


if __name__ == "__main__":
    # Example queries
    debug_retriever("NousResearch/hermes-agent", "How does the agent handle memory?")
    # Or try your own query:
    # debug_retriever("NousResearch/hermes-agent", "Your custom query here")