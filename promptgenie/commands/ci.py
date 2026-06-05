from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table
from rich import box

from promptgenie.core.ci import init_ci, ci_status
from promptgenie.renderers.rich import console

_CI_LABELS = {
    "github_actions": "GitHub Actions workflow",
    "pre_commit":     "pre-commit config",
    "promptignore":   ".promptignore",
    "is_git_repo":    "Git repository",
}


@click.group(name="ci")
def ci_group():
    """Set up and check CI integrations for prompt quality gates."""


@ci_group.command(name="init")
@click.option("--dir", "target_dir", default=".", type=click.Path(),
              help="Target project directory (default: current directory).")
def ci_init(target_dir):
    """Scaffold GitHub Actions workflow and pre-commit hooks for prompt checks."""
    result = init_ci(target_dir)

    console.print()
    for key, path in result.get("created", {}).items():
        console.print(f"  [green]Created[/green]  {_CI_LABELS.get(key, key)}: [dim]{path}[/dim]")
    for key, path in result.get("skipped", {}).items():
        console.print(f"  [yellow]Skipped[/yellow] {_CI_LABELS.get(key, key)}: already exists at [dim]{path}[/dim]")

    console.print()
    console.print(Panel(
        "\n".join([
            "[bold]GitHub Actions[/bold]",
            "Push or PR touching [dim].md[/dim] / [dim].prompt-test.yaml[/dim] / [dim].workflow.yaml[/dim] files",
            "will automatically run lint, scan, and test jobs.",
            "",
            "[bold]Pre-commit hooks[/bold]",
            "Install with: [cyan]pip install pre-commit && pre-commit install[/cyan]",
            "Hooks run on staged [dim].prompt.md[/dim] and [dim].prompt-test.yaml[/dim] files.",
            "",
            "[bold].promptignore[/bold]",
            "Add paths to exclude from lint/scan checks (supports glob patterns).",
        ]),
        title="CI Integration Ready",
        border_style="green",
    ))


@ci_group.command(name="status")
@click.option("--dir", "target_dir", default=".", type=click.Path(),
              help="Target project directory (default: current directory).")
def ci_status_cmd(target_dir):
    """Check which CI integrations are active in a project directory."""
    status = ci_status(target_dir)

    table = Table(title=f"CI Status — {Path(target_dir).resolve()}", box=box.ROUNDED)
    table.add_column("Integration")
    table.add_column("Status", justify="center")
    for key, active in status.items():
        icon = "[green]✓ Active[/green]" if active else "[dim]✗ Not found[/dim]"
        table.add_row(_CI_LABELS.get(key, key), icon)
    console.print(table)

    if not status.get("is_git_repo"):
        console.print("\n[yellow]Warning:[/yellow] No .git directory found — not a git repository.")
    if not all(status.values()):
        console.print("\n[dim]Run [bold]promptgenie ci init[/bold] to set up missing integrations.[/dim]")
