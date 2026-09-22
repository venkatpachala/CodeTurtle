"""core/output/terminal.py — Rich console renderer for ReviewFinding list."""

from __future__ import annotations

from typing import Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from core.review.finding import ReviewFinding

_SEVERITY_COLORS = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
}

_VERIFICATION_ICONS = {
    "verified": "✅",
    "uncertain": "⚠️ ",
    "disproved": "❌",
    "candidate": "🔍",
}


def render_findings_terminal(
    findings: "List[ReviewFinding]",
    *,
    show_uncertain: bool = False,
    console: Any = None,
) -> None:
    """Print formatted findings to the Rich console.

    Args:
        findings: List of ReviewFinding objects.
        show_uncertain: Whether to show findings with uncertain verification.
        console: Rich Console instance. Creates one if not provided.
    """
    try:
        from rich.console import Console as _Console
        from rich.panel import Panel
        from rich.markdown import Markdown
        from rich.text import Text

        con = console or _Console()
    except ImportError:
        _fallback_print(findings, show_uncertain=show_uncertain)
        return

    from core.review.finding import VERIFICATION_DISPROVED, VERIFICATION_UNCERTAIN

    visible = [
        f for f in findings
        if f.verification_status != VERIFICATION_DISPROVED
        and (show_uncertain or f.verification_status != VERIFICATION_UNCERTAIN)
    ]

    if not visible:
        con.print("[dim]No validated findings.[/dim]")
        return

    for i, finding in enumerate(visible, 1):
        color = _SEVERITY_COLORS.get(finding.severity, "white")
        icon = _VERIFICATION_ICONS.get(finding.verification_status, "")
        header = Text()
        header.append(f"{icon} [{i}] ", style="bold")
        header.append(f"[{finding.severity.upper()}] ", style=color)
        header.append(finding.title, style="bold")
        header.append(f"  {finding.file}", style="dim")
        if finding.line:
            header.append(f":{finding.line}", style="dim")

        body = f"{finding.claim}\n"
        if finding.existing_code:
            body += f"\n```\n{finding.existing_code.strip()}\n```\n"
        if finding.violating_condition:
            body += f"\n**When:** {finding.violating_condition}\n"
        if finding.execution_path:
            body += f"\n**Call path:** `{'` → `'.join(finding.execution_path)}`\n"

        meta = (
            f"*Confidence: {int(finding.confidence * 100)}% · "
            f"Verification: {finding.verification_status} · "
            f"Bundle: {finding.bundle_id or '?'}*"
        )
        body += f"\n{meta}"

        con.print(header)
        con.print(Panel(Markdown(body), border_style=color, padding=(0, 1)))

    con.print(f"\n[bold]{len(visible)} finding(s) displayed.[/bold]")


def _fallback_print(findings: "List[ReviewFinding]", *, show_uncertain: bool = False) -> None:
    """Minimal fallback when Rich is not available."""
    from core.review.finding import VERIFICATION_DISPROVED, VERIFICATION_UNCERTAIN

    for f in findings:
        if f.verification_status == VERIFICATION_DISPROVED:
            continue
        if not show_uncertain and f.verification_status == VERIFICATION_UNCERTAIN:
            continue
        print(f"\n[{f.severity.upper()}] {f.title}")
        print(f"  File: {f.file}:{f.line}")
        print(f"  {f.claim}")
