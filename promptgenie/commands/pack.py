import sys
from pathlib import Path

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.context_packs import (
    init_pack,
    inject_pack_into_prompt,
    list_packs,
    load_pack,
    render_pack,
)
from promptgenie.renderers.rich import console


@click.group(name="pack")
def pack_group():
    """Manage context packs — reusable project context blocks."""


@pack_group.command(name="list")
def pack_list():
    """List all available context packs."""
    packs = list_packs()
    if not packs:
        console.print(
            "[dim]No context packs found. Run [bold]promptgenie pack init <id>[/bold] to create one.[/dim]"
        )
        return
    table = Table(title="Context Packs", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Description", style="dim")
    table.add_column("Stack", style="dim")
    for p in packs:
        stack = ", ".join(p["stack"][:3])
        if len(p["stack"]) > 3:
            stack += f" +{len(p['stack']) - 3} more"
        table.add_row(p["id"], p["name"], p["description"], stack)
    console.print(table)


@pack_group.command(name="show")
@click.argument("pack_id")
@click.option(
    "--mode",
    "-m",
    default="standard",
    type=click.Choice(["minimal", "standard", "exhaustive"]),
    help="How much of the pack to render.",
)
def pack_show(pack_id, mode):
    """Show the rendered context block for a pack."""
    try:
        rendered = render_pack(pack_id, mode=mode)
        pack = load_pack(pack_id)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    console.print(
        Panel(
            rendered,
            title=f"Context Pack — {pack.get('name', pack_id)}  [dim]mode: {mode}[/dim]",
            border_style="cyan",
        )
    )


@pack_group.command(name="inject")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.argument("pack_id")
@click.option(
    "--mode", "-m", default="standard", type=click.Choice(["minimal", "standard", "exhaustive"])
)
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(),
    help="Save result to file (defaults to overwrite prompt_file).",
)
def pack_inject(prompt_file, pack_id, mode, out):
    """Inject a context pack into an existing prompt file."""
    try:
        prompt_text = Path(prompt_file).read_text()
        result = inject_pack_into_prompt(prompt_text, pack_id, mode=mode)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    dest = out or prompt_file
    Path(dest).write_text(result)
    console.print(Panel(result, title=f"Injected — {pack_id} → {dest}", border_style="cyan"))
    console.print(f"[green]Saved to {dest}[/green]")


@pack_group.command(name="init")
@click.argument("pack_id")
@click.option("--name", default="", help="Human-readable name for the pack.")
@click.option("--description", default="", help="One-line description.")
def pack_init(pack_id, name, description):
    """Create a new blank context pack file."""
    try:
        path = init_pack(pack_id, name=name, description=description)
        console.print(f"[green]Created context pack:[/green] {path}")
        console.print("[dim]Edit the file to fill in your project details, then use:[/dim]")
        console.print(f'  promptgenie generate "your task" --pack {pack_id}')
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
