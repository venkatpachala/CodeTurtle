import json
from pathlib import Path
from collections import Counter
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.repository_intelligence import RepositoryIntelligence

console = Console()


def verify_repository_model(repo_name: str):
    """Accurate verification using the same scanning logic as the indexer."""

    repo_path = Path("repos") / repo_name.replace("/", "_")
    model_path = Path(".codeturtle/repositories") / repo_name.replace("/", "_") / "repository_model.json"

    console.print(Panel.fit(
        f"[bold cyan]Repository Model Verification[/bold cyan]\n\n{repo_name}",
        title="CodeTurtle"
    ))

    if not model_path.exists():
        console.print("[red]Error: repository_model.json not found.[/red]")
        return False

    # Load model
    with open(model_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    files_in_model = data.get("files", [])
    model_file_paths = {f["path"] for f in files_in_model}

    print(f"Total files in model: {len(files_in_model)}")

    # Reuse the exact scanner logic from RepositoryIntelligence
    intelligence = RepositoryIntelligence(str(repo_path), repo_name)
    actual_files = list(intelligence._scan_files())  # Reuse internal scanner

    actual_file_paths = {str(f.relative_to(repo_path)) for f in actual_files}

    print(f"Total relevant files on disk (scanner): {len(actual_files)}")

    # Verification table
    table = Table(title="Verification Results")
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details", style="white")

    # 1. Bidirectional mapping
    missing_on_disk = model_file_paths - actual_file_paths
    missing_in_model = actual_file_paths - model_file_paths

    table.add_row("All model files exist on disk", 
                  "[red]FAIL[/red]" if missing_on_disk else "[green]PASS[/green]", 
                  f"Missing: {len(missing_on_disk)}")

    table.add_row("All scanned files in model", 
                  "[red]FAIL[/red]" if missing_in_model else "[green]PASS[/green]", 
                  f"Missing: {len(missing_in_model)}")

    # 2. Content & metadata integrity
    empty_content = 0
    content_mismatch = 0
    line_mismatch = 0

    for fm in files_in_model:
        full_path = repo_path / fm["path"]
        if not full_path.exists():
            continue

        disk_content = full_path.read_text(encoding="utf-8", errors="ignore")
        model_content = fm.get("content", "")

        if not model_content.strip():
            empty_content += 1
        elif disk_content != model_content:
            content_mismatch += 1

        disk_lines = len(disk_content.splitlines())
        if disk_lines != fm.get("line_count", 0):
            line_mismatch += 1

    table.add_row("Files have non-empty content", 
                  "[red]FAIL[/red]" if empty_content else "[green]PASS[/green]", 
                  f"Empty: {empty_content}")

    table.add_row("Content matches disk", 
                  "[red]FAIL[/red]" if content_mismatch else "[green]PASS[/green]", 
                  f"Mismatches: {content_mismatch}")

    table.add_row("line_count matches", 
                  "[red]FAIL[/red]" if line_mismatch else "[green]PASS[/green]", 
                  f"Mismatches: {line_mismatch}")

    # 3. Metadata summary
    language_count = Counter(f.get("language", "unknown") for f in files_in_model)
    symbol_count = sum(len(f.get("symbols", [])) for f in files_in_model)

    table.add_row("Metadata summary", "[green]INFO[/green]", 
                  f"Languages: {dict(language_count)} | Symbols: {symbol_count}")

    console.print(table)

    if missing_on_disk or missing_in_model or empty_content or content_mismatch or line_mismatch:
        console.print("[red]Some checks failed.[/red]")
        if missing_on_disk:
            console.print("\n[red]Files in model but missing on disk:[/red]")
            for f in sorted(missing_on_disk):
                console.print(f"  - {f}")
        if missing_in_model:
            console.print("\n[red]Files on disk but missing in model:[/red]")
            for f in sorted(missing_in_model):
                console.print(f"  - {f}")
    else:
        console.print("[green]✓ Repository model is consistent with disk and scanner.[/green]")

    return True


if __name__ == "__main__":
    verify_repository_model("NousResearch/hermes-agent")