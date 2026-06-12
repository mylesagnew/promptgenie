"""trust.py — ``promptgenie trust`` command group (S-2).

Manage the spec trust store that gates automatic execution of a spec's
host-touching context sources (cmd / file / glob / env / url).

Commands
--------
  promptgenie trust list                 show trusted specs
  promptgenie trust add <spec>           trust a spec's context sources
  promptgenie trust revoke <spec>        revoke trust for a spec
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import click

from promptgenie.core.errors import EXIT_USAGE
from promptgenie.core.trust import (
    add_trust,
    is_trusted,
    list_trusted,
    revoke_trust,
)
from promptgenie.renderers.rich import console, diag_console


@click.group("trust", help="Manage trusted PromptSpecs (gates context-source execution).")
def trust_group() -> None:
    pass


@trust_group.command("list")
def trust_list_cmd() -> None:
    """List all trusted specs.

    Example:

      promptgenie trust list
    """
    records = list_trusted()
    if not records:
        console.print("[dim]No trusted specs. Run 'promptgenie trust add <spec>' to add one.[/dim]")
        return

    from rich.table import Table

    table = Table(title="Trusted Specs", show_header=True, header_style="bold")
    table.add_column("Path", style="cyan")
    table.add_column("Content hash")
    table.add_column("Trusted at")

    for rec in records:
        ts = rec.get("trusted_at", 0)
        when = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else "—"
        chash = str(rec.get("content_hash", ""))[:12]
        table.add_row(str(rec.get("path", "")), chash, when)
    console.print(table)


@trust_group.command("add")
@click.argument("spec_file", type=click.Path(exists=True))
def trust_add_cmd(spec_file: str) -> None:
    """Trust a spec's context sources.

    Example:

      promptgenie trust add my-prompt.yaml
    """
    path = Path(spec_file)
    add_trust(path)
    console.print(f"[green]✓[/green] Trusted spec: {path.resolve()}")


@trust_group.command("revoke")
@click.argument("spec_file", type=click.Path())
def trust_revoke_cmd(spec_file: str) -> None:
    """Revoke trust for a spec.

    Example:

      promptgenie trust revoke my-prompt.yaml
    """
    path = Path(spec_file)
    was_trusted = is_trusted(path)
    revoke_trust(path)
    if was_trusted:
        console.print(f"[green]✓[/green] Revoked trust for: {path.resolve()}")
    else:
        diag_console.print(f"[yellow]Spec was not trusted:[/yellow] {path.resolve()}")
        raise SystemExit(EXIT_USAGE)
