"""Shared Rich terminal rendering utilities."""

from rich import box  # noqa: F401  — re-exported for command modules
from rich.console import Console
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

console = Console()

SEVERITY_COLORS = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan", "INFO": "dim"}
RISK_COLORS = {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan"}
SCORE_COLORS = [(80, "green"), (60, "yellow"), (0, "red")]


def score_color(n: int) -> str:
    for threshold, color in SCORE_COLORS:
        if n >= threshold:
            return color
    return "red"


def format_lint_issues(result) -> str:
    if not result.issues:
        return "[green]No issues found.[/green]"
    lines = []
    for issue in result.issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lines.append(f"[{color}][{issue.severity}][/{color}] [{issue.code}] {issue.message}")
        if issue.suggestion:
            lines.append(f"  [dim]→ {issue.suggestion}[/dim]")
    return "\n".join(lines)


def format_scan_findings(result) -> str:
    if not result.findings:
        return "[green]No findings.[/green]"
    lines = []
    for f in result.findings:
        color = RISK_COLORS.get(f.risk, "white")
        lines.append(f"[{color}][{f.risk}][/{color}] [{f.code}] {f.message}")
        if f.recommendation:
            lines.append(f"  [dim]→ {f.recommendation}[/dim]")
    return "\n".join(lines)


def delta_str(n: int, invert: bool = False) -> str:
    """Coloured +/- string for a pre-computed integer delta."""
    color = (
        "green" if (n > 0 and not invert) or (n < 0 and invert) else ("red" if n != 0 else "dim")
    )
    prefix = "+" if n > 0 else ""
    return f"[{color}]{prefix}{n}[/{color}]"


def delta_ab(a: int, b: int, invert: bool = False) -> str:
    """Coloured +/- string for b - a (used in adapt summary table)."""
    d = b - a
    color = (
        "green" if (d > 0 and not invert) or (d < 0 and invert) else ("red" if d != 0 else "dim")
    )
    prefix = "+" if d > 0 else ""
    return f"[{color}]{prefix}{d}[/{color}]"
