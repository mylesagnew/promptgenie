"""audit.py — ``promptgenie audit`` command group.

Commands
--------
  promptgenie audit list               list recent audit events
  promptgenie audit show <id>          show detail for a specific event
  promptgenie audit export <file>      export audit log to file
  promptgenie audit verify             verify the tamper-evident chain
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from promptgenie.core.audit import (
    export_audit,
    list_audit_events,
    load_audit_event,
    verify_chain,
    _AUDIT_DB,
)
from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.renderers.rich import console, diag_console, is_structured_mode


@click.group("audit", help="Inspect and export the run audit log.")
def audit_group() -> None:
    pass


# ---------------------------------------------------------------------------
# audit list
# ---------------------------------------------------------------------------


@audit_group.command("list")
@click.option("--limit", default=20, show_default=True, type=int,
              help="Maximum number of events to show.")
@click.option("--command", default=None,
              help="Filter by command name (e.g. run, analyze).")
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json", "yaml"], case_sensitive=False),
              default="rich", show_default=True)
def audit_list_cmd(limit: int, command: str | None, output_format: str) -> None:
    """List recent audit events.

    \b
    Examples:
      promptgenie audit list
      promptgenie audit list --limit 50 --command run
      promptgenie audit list --format json | jq '.[] | select(.external_send)'
    """
    events = list_audit_events(limit=limit, command=command)

    if not events:
        if not _AUDIT_DB.exists():
            diag_console.print("[dim]No audit log found. Run a command to create one.[/dim]")
        else:
            diag_console.print("[dim]No events found.[/dim]")
        raise SystemExit(EXIT_OK)

    if is_structured_mode(output_format):
        data = [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "user": e.user,
                "command": e.command,
                "provider": e.provider,
                "model": e.model,
                "spec_name": e.spec_name,
                "policy_decision": e.policy_decision,
                "external_send": e.external_send,
                "status": e.status,
                "prompt_hash": e.prompt_hash,
                "row_hash": e.row_hash[:12],
            }
            for e in events
        ]
        if output_format == "yaml":
            sys.stdout.write(yaml.dump(data, default_flow_style=False))
        else:
            sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return

    from rich.table import Table
    table = Table(title=f"Audit Log ({len(events)} events)", show_header=True, header_style="bold")
    table.add_column("ID", width=5, justify="right")
    table.add_column("Timestamp", no_wrap=True)
    table.add_column("Command", width=10)
    table.add_column("Provider")
    table.add_column("Spec")
    table.add_column("Policy")
    table.add_column("Ext", width=4)
    table.add_column("Status")

    for e in events:
        ts = e.timestamp[:19].replace("T", " ")
        policy_color = "green" if e.policy_decision == "pass" else (
            "red" if e.policy_decision == "fail" else "dim"
        )
        ext_flag = "[yellow]✓[/yellow]" if e.external_send else "—"
        status_color = "green" if e.status == "ok" else (
            "red" if e.status == "error" else "dim"
        )
        table.add_row(
            str(e.id),
            ts,
            e.command or "—",
            e.provider or "—",
            (e.spec_name or "—")[:20],
            f"[{policy_color}]{e.policy_decision}[/{policy_color}]",
            ext_flag,
            f"[{status_color}]{e.status}[/{status_color}]",
        )
    console.print(table)
    console.print(f"[dim]Audit DB: {_AUDIT_DB}[/dim]")


# ---------------------------------------------------------------------------
# audit show
# ---------------------------------------------------------------------------


@audit_group.command("show")
@click.argument("event_id", type=int)
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json", "yaml"], case_sensitive=False),
              default="rich", show_default=True)
def audit_show_cmd(event_id: int, output_format: str) -> None:
    """Show detail for a specific audit event by ID.

    Example:
      promptgenie audit show 42
      promptgenie audit show 42 --format json
    """
    event = load_audit_event(event_id)
    if not event:
        diag_console.print(f"[red]Audit event {event_id} not found.[/red]")
        raise SystemExit(EXIT_USAGE)

    data = {
        "id": event.id,
        "timestamp": event.timestamp,
        "user": event.user,
        "cwd": event.cwd,
        "command": event.command,
        "provider": event.provider,
        "model": event.model,
        "spec_name": event.spec_name,
        "prompt_hash": event.prompt_hash,
        "response_hash": event.response_hash,
        "policy_decision": event.policy_decision,
        "external_send": event.external_send,
        "status": event.status,
        "row_hash": event.row_hash,
        "extra": event.extra,
    }

    if is_structured_mode(output_format):
        if output_format == "yaml":
            sys.stdout.write(yaml.dump(data, default_flow_style=False))
        else:
            sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return

    console.print(f"\n[bold]Audit Event #{event.id}[/bold]")
    for k, v in data.items():
        if k == "extra" and v:
            console.print(f"  extra:")
            for ek, ev in v.items():
                console.print(f"    {ek}: {ev}")
        elif v or v == 0:
            console.print(f"  {k}: {v}")
    console.print()


# ---------------------------------------------------------------------------
# audit export
# ---------------------------------------------------------------------------


@audit_group.command("export")
@click.argument("output_file", type=click.Path())
@click.option("--format", "output_format",
              type=click.Choice(["json", "csv", "ndjson"], case_sensitive=False),
              default="json", show_default=True)
@click.option("--limit", default=1000, show_default=True, type=int,
              help="Maximum number of events to export.")
def audit_export_cmd(output_file: str, output_format: str, limit: int) -> None:
    """Export audit log to a file.

    \b
    Examples:
      promptgenie audit export audit.json
      promptgenie audit export audit.csv --format csv
      promptgenie audit export audit.ndjson --format ndjson --limit 500
    """
    try:
        export_audit(output_file, fmt=output_format, limit=limit)
        console.print(
            f"[green]✓[/green] Exported up to {limit} events to "
            f"[bold]{output_file}[/bold] ({output_format})"
        )
    except Exception as exc:
        diag_console.print(f"[red]Export failed:[/red] {exc}")
        raise SystemExit(EXIT_FAILURE)


# ---------------------------------------------------------------------------
# audit verify
# ---------------------------------------------------------------------------


@audit_group.command("verify")
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json"], case_sensitive=False),
              default="rich", show_default=True)
def audit_verify_cmd(output_format: str) -> None:
    """Verify the tamper-evident hash chain of the audit log.

    Exits 0 if the chain is intact, 1 if tampering is detected.

    Example:
      promptgenie audit verify
    """
    ok, broken_id = verify_chain()

    if is_structured_mode(output_format):
        sys.stdout.write(json.dumps({
            "valid": ok,
            "first_broken_id": broken_id,
        }, indent=2) + "\n")
    else:
        if ok:
            console.print("[green]✓[/green] Audit chain is intact.")
        else:
            console.print(
                f"[red]✗[/red] Audit chain broken at event ID {broken_id}. "
                "Possible tampering detected."
            )

    raise SystemExit(EXIT_OK if ok else EXIT_FAILURE)
