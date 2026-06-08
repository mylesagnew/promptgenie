import sys

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.adapter import adapt
from promptgenie.core.fileio import safe_write_text
from promptgenie.renderers.rich import console, delta_ab


@click.command(name="adapt")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.option(
    "--from", "from_target", required=True, help="Source target profile (e.g. claude-code)."
)
@click.option("--to", "to_target", required=True, help="Destination target profile (e.g. cursor).")
@click.option("--out", "-o", default=None, type=click.Path(), help="Save adapted prompt to file.")
@click.option("--force", is_flag=True, help="Overwrite --out file if it already exists.")
@click.option(
    "--show-original", is_flag=True, help="Print original prompt alongside adapted version."
)
@click.option(
    "--strip-agentic-safety",
    "strip_agentic_safety",
    is_flag=True,
    help="Remove agentic safety sections (stop conditions, scope, forbidden actions, etc.) "
    "when adapting to a non-agentic target. Off by default — safety sections are preserved.",
)
@click.option(
    "--best-effort",
    is_flag=True,
    help=(
        "Fall back to empty profile stubs when --from or --to profile is not found, "
        "instead of aborting with an error. Without this flag, unknown profile names are "
        "fatal errors."
    ),
)
def adapt_cmd(prompt_file, from_target, to_target, out, force, show_original, strip_agentic_safety, best_effort):
    """Translate a prompt from one target profile to another."""
    try:
        with console.status("[bold blue]Adapting prompt…"):
            result = adapt(
                prompt_file,
                from_target,
                to_target,
                strip_agentic_safety=strip_agentic_safety,
                best_effort=best_effort,
            )
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        console.print("[dim]Use --best-effort to fall back to empty profile stubs.[/dim]")
        sys.exit(1)

    from_name = result.source_target
    to_name = result.dest_target
    console.print()

    if show_original:
        console.print(
            Panel(
                result.original_text, title=f"[dim]Original — {from_name}[/dim]", border_style="dim"
            )
        )

    console.print(
        Panel(
            result.adapted_text,
            title=f"[bold]Adapted Prompt[/bold]  [dim]{from_name}[/dim] → [cyan]{to_name}[/cyan]",
            border_style="blue",
        )
    )

    ACTION_STYLE = {
        "kept": ("dim", "KEPT"),
        "rewritten": ("yellow", "REWRITTEN"),
        "added": ("green", "ADDED"),
        "dropped": ("red", "DROPPED"),
    }
    change_lines = []
    for change in result.changes:
        if change.name == "":
            continue
        color, label = ACTION_STYLE.get(change.action, ("white", change.action.upper()))
        change_lines.append(f"[{color}][{label}][/{color}]  {change.name}")
        change_lines.append(f"  [dim]{change.reason}[/dim]")
    console.print(Panel("\n".join(change_lines), title="Change Log", border_style="dim"))

    summary = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    summary.add_column("Metric", style="dim")
    summary.add_column(f"Original ({from_name})", justify="right")
    summary.add_column(f"Adapted ({to_name})", justify="right")
    summary.add_row(
        "Tokens",
        str(result.source_tokens),
        str(result.adapted_tokens)
        + f"  {delta_ab(result.source_tokens, result.adapted_tokens, invert=True)}",
    )
    summary.add_row(
        "Quality score",
        f"{result.source_score['total']}/100",
        f"{result.adapted_score['total']}/100  {delta_ab(result.source_score['total'], result.adapted_score['total'])}",
    )
    console.print(Panel(summary, title="Score & Token Summary", border_style="dim"))

    if result.warnings:
        warn_lines = "\n".join(f"[yellow]⚠[/yellow]  {w}" for w in result.warnings)
        console.print(Panel(warn_lines, title="Warnings", border_style="yellow"))

    if out:
        try:
            safe_write_text(out, result.adapted_text, force=force)
            console.print(f"\n[green]Adapted prompt saved to {out}[/green]")
        except FileExistsError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
