import sys

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
from promptgenie.core.fileio import FileTooLargeError, safe_read_text, safe_write_text
from promptgenie.renderers.rich import console


@click.group(name="pack")
def pack_group():
    """Manage context packs and registry rule packs."""


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
@click.option("--force", is_flag=True, help="Overwrite --out file if it already exists.")
def pack_inject(prompt_file, pack_id, mode, out, force):
    """Inject a context pack into an existing prompt file."""
    try:
        prompt_text = safe_read_text(prompt_file)
        result = inject_pack_into_prompt(prompt_text, pack_id, mode=mode)
    except (FileNotFoundError, FileTooLargeError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    dest = out or prompt_file
    # Injecting back into the source file is always an intentional overwrite
    dest_force = force or (dest == prompt_file)
    try:
        safe_write_text(dest, result, force=dest_force)
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    console.print(Panel(result, title=f"Injected — {pack_id} → {dest}", border_style="cyan"))
    console.print(f"[green]Saved to {dest}[/green]")


@pack_group.command(name="search")
@click.argument("query", required=False, default="")
def pack_search(query: str):
    """Search the registry index for available packs."""
    from promptgenie.core.registry import load_index

    entries = load_index()
    if query:
        q = query.lower()
        entries = [
            e
            for e in entries
            if q in e.id.lower() or q in e.name.lower() or q in e.description.lower()
        ]

    if not entries:
        console.print("[dim]No packs found matching your query.[/dim]")
        return

    table = Table(title="Registry Packs", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Version", style="dim")
    table.add_column("Type", style="dim")
    table.add_column("Description", style="dim")
    for e in entries:
        table.add_row(e.id, e.name, e.version, e.type, e.description)
    console.print(table)


@pack_group.command(name="install")
@click.argument("pack_id")
@click.option("--timeout", default=30, type=int, help="Download timeout in seconds.")
def pack_install(pack_id: str, timeout: int):
    """Download and install a pack from the registry."""
    from promptgenie.core.registry import install_pack, load_index

    entries = load_index()
    matching = [e for e in entries if e.id == pack_id]
    if not matching:
        console.print(f"[red]Error:[/red] Pack {pack_id!r} not found in registry.")
        console.print(
            "[dim]Run [bold]promptgenie pack search[/bold] to list available packs.[/dim]"
        )
        sys.exit(1)

    entry = matching[0]
    console.print(f"Installing [bold]{entry.name}[/bold] [dim]v{entry.version}[/dim]…")
    try:
        path = install_pack(entry, timeout=timeout)
        console.print(f"[green]✓[/green] Installed to {path}")
    except ValueError as e:
        console.print(f"[red]Checksum error:[/red] {e}")
        sys.exit(1)
    except OSError as e:
        console.print(f"[red]Download failed:[/red] {e}")
        sys.exit(1)


@pack_group.command(name="update")
@click.option("--url", default=None, help="Registry index URL (overrides default).")
@click.option("--timeout", default=30, type=int, help="Download timeout in seconds.")
def pack_update(url: str | None, timeout: int):
    """Fetch the remote registry and install/update all packs."""
    from promptgenie.core.registry import DEFAULT_REGISTRY_URL, update_registry

    registry_url = url or DEFAULT_REGISTRY_URL
    console.print(f"[dim]Fetching registry from {registry_url}…[/dim]")
    result = update_registry(url=registry_url, timeout=timeout)

    if result.installed:
        console.print(f"[green]Installed:[/green] {', '.join(result.installed)}")
    if result.updated:
        console.print(f"[blue]Updated:[/blue]   {', '.join(result.updated)}")
    if result.skipped:
        console.print(f"[dim]Up-to-date: {', '.join(result.skipped)}[/dim]")
    if result.errors:
        for err in result.errors:
            console.print(f"[red]Error:[/red] {err}")
        sys.exit(1)

    if not result.installed and not result.updated and not result.errors:
        console.print("[dim]All packs are up to date.[/dim]")


@pack_group.command(name="dirs")
def pack_dirs():
    """Show registry and user rules directories."""
    from promptgenie.core.registry import (
        BUILTIN_PACKS_DIR,
        CACHED_INDEX_PATH,
        USER_PACKS_DIR,
        USER_RULES_DIR,
    )

    table = Table(title="Pack Directories", box=box.ROUNDED, show_header=True)
    table.add_column("Purpose", style="cyan")
    table.add_column("Path")
    table.add_column("Exists", style="dim")

    dirs = [
        ("Built-in packs (shipped)", BUILTIN_PACKS_DIR),
        ("Installed packs (registry)", USER_PACKS_DIR),
        ("Custom rules dir", USER_RULES_DIR),
        ("Cached index", CACHED_INDEX_PATH),
    ]
    for label, path in dirs:
        exists = "✓" if path.exists() else "—"
        table.add_row(label, str(path), exists)
    console.print(table)


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
