from github import Github
from core.hybrid_retriever import HybridRetriever
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


def debug_retrieval_full(repo_name: str, pr_number: int):
    """Show exactly what is retrieved and passed to agents."""

    console.print(Panel.fit(
        f"[bold cyan]Full Retrieval Debug[/bold cyan]\n\n{repo_name}#{pr_number}",
        title="CodeTurtle"
    ))

    # Fetch PR
    g = Github()  # Use token if needed
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    print(f"PR Title: {pr.title}")
    print(f"PR Body: {pr.body[:300]}..." if pr.body else "No body")

    # Build query
    query = f"{pr.title}\n{pr.body or ''}"

    # Hybrid Retrieval
    retriever = HybridRetriever(repo_name)
    retrieved_docs = retriever.retrieve(query, k=8)

    print(f"\n[bold yellow]Retrieved {len(retrieved_docs)} documents from Knowledge Base[/bold yellow]\n")

    # Show full retrieved data
    for i, doc in enumerate(retrieved_docs):
        print(f"--- Document {i+1} ---")
        print(f"Path: {doc.metadata.get('path', 'N/A')}")
        print(f"Retrieval Type: {doc.metadata.get('retrieval_type', 'vector')}")
        print(f"Content:\n{doc.page_content}\n")

    # Show what would be passed to first agent (Context Summarizer)
    raw_context = "\n\n".join([doc.page_content[:800] for doc in retrieved_docs])
    print("\n[bold cyan]=== CONTEXT PASSED TO FIRST AGENT (Context Summarizer) ===[/bold cyan]")
    print(raw_context[:2000] + "..." if len(raw_context) > 2000 else raw_context)

    # Save to file
    with open(f"debug_full_{repo_name.replace('/', '_')}_{pr_number}.txt", "w", encoding="utf-8") as f:
        f.write(f"PR: {repo_name}#{pr_number}\n")
        f.write(f"Query: {query}\n\n")
        f.write("Retrieved Documents:\n")
        for i, doc in enumerate(retrieved_docs):
            f.write(f"\nDocument {i+1}\n")
            f.write(f"Path: {doc.metadata.get('path')}\n")
            f.write(f"Content:\n{doc.page_content}\n")
        f.write("\nContext Passed to First Agent:\n")
        f.write(raw_context)

    print("\n[green]Full debug output saved to file.[/green]")


if __name__ == "__main__":
    debug_retrieval_full("FalkorDB/QueryWeaver", 571)