"""history_cmd.py — ``promptgenie history`` command group.

Subcommands
-----------
  history list    list recent runs from the SQLite history database
  history show    show full detail for a single run
  history diff    unified diff between two run responses
  history replay  re-send a historical run's prompt to the same provider
  history export  export run history to JSON / CSV / NDJSON
  history clear   delete all history (with confirmation)

Examples
--------
  promptgenie history list
  promptgenie history list --limit 50 --provider claude
  promptgenie history show <run-id>
  promptgenie history diff <run-id-a> <run-id-b>
  promptgenie history replay <run-id>
  promptgenie history export --format csv > runs.csv
  promptgenie history clear --yes
"""

from __future__ import annotations

import sys

import click

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.renderers.rich import console, diag_console


@click.group("history", help="Browse and manage prompt run history.")
def history_group() -> None:
    pass


# ---------------------------------------------------------------------------
# history list
# ---------------------------------------------------------------------------

@history_group.command("list")
@click.option("--limit", "-n", default=20, type=int, show_default=True)
@click.option("--provider", default=None, help="Filter by provider name.")
@click.option("--status", default=None,
              type=click.Choice(["ok", "error", "dry_run"], case_sensitive=False))
@click.option("--spec", "spec_name", default=None, help="Filter by spec name (partial match).")
@click.option("--search", default=None, help="Full-text search across prompt/spec/provider.")
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json"], case_sensitive=False),
              default="rich", show_default=True)
@click.option("--db", "db_path", default=None, type=click.Path(), help="Custom DB path.")
def history_list_cmd(
    limit: int,
    provider: str | None,
    status: str | None,
    spec_name: str | None,
    search: str | None,
    output_format: str,
    db_path: str | None,
) -> None:
    """List recent prompt runs from history.

    \b
    Examples:
      promptgenie history list
      promptgenie history list --limit 50 --provider claude
      promptgenie history list --search "auth prompt"
    """
    from pathlib import Path
    from promptgenie.core.history_db import open_history_db

    with open_history_db(Path(db_path) if db_path else None) as db:
        if search:
            records = db.search_runs(search, limit=limit)
        else:
            records = db.list_runs(
                limit=limit, provider=provider, status=status, spec_name=spec_name
            )

    if not records:
        console.print("[dim]No history found.[/dim]")
        raise SystemExit(EXIT_OK)

    if output_format == "json":
        import json
        sys.stdout.write(json.dumps([r.to_dict() for r in records], indent=2) + "\n")
        return

    from rich.table import Table
    table = Table(title="Run History", show_header=True, header_style="bold")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Spec")
    table.add_column("Provider", no_wrap=True)
    table.add_column("Model", no_wrap=True)
    table.add_column("Status", width=7)
    table.add_column("Started", no_wrap=True)
    table.add_column("Duration", justify="right", width=8)
    table.add_column("Tokens", justify="right", width=7)

    _STATUS_COLORS = {"ok": "green", "error": "red", "dry_run": "yellow"}
    for r in records:
        color = _STATUS_COLORS.get(r.status, "dim")
        table.add_row(
            r.id[:8],
            r.spec_name or "—",
            r.provider or "—",
            r.model or "—",
            f"[{color}]{r.status}[/{color}]",
            r.started_at[:19].replace("T", " "),
            f"{r.duration_s:.1f}s",
            str(r.input_tokens + r.output_tokens),
        )

    console.print(table)
    console.print(f"[dim]{len(records)} run(s)[/dim]")


# ---------------------------------------------------------------------------
# history show
# ---------------------------------------------------------------------------

@history_group.command("show")
@click.argument("run_id")
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json", "raw"], case_sensitive=False),
              default="rich", show_default=True)
@click.option("--db", "db_path", default=None, type=click.Path())
def history_show_cmd(run_id: str, output_format: str, db_path: str | None) -> None:
    """Show full details of a run.

    \b
    Example:
      promptgenie history show abc12345
    """
    from pathlib import Path
    from promptgenie.core.history_db import open_history_db
    from rich.panel import Panel

    with open_history_db(Path(db_path) if db_path else None) as db:
        # Support prefix matching
        if len(run_id) < 36:
            records = db.list_runs(limit=1000)
            matches = [r for r in records if r.id.startswith(run_id)]
            record = matches[0] if matches else None
        else:
            record = db.get_run(run_id)

    if record is None:
        diag_console.print(f"[red]Error:[/red] Run {run_id!r} not found.")
        raise SystemExit(EXIT_USAGE)

    if output_format == "json":
        import json
        d = record.to_dict()
        d["prompt_text"] = record.prompt_text
        d["response_text"] = record.response_text
        sys.stdout.write(json.dumps(d, indent=2) + "\n")
        return

    if output_format == "raw":
        sys.stdout.write(record.response_text + "\n")
        return

    console.print(Panel(
        f"[bold]ID:[/bold] {record.id}\n"
        f"[bold]Spec:[/bold] {record.spec_name or '—'}\n"
        f"[bold]Provider:[/bold] {record.provider} / {record.model}\n"
        f"[bold]Status:[/bold] {record.status}\n"
        f"[bold]Started:[/bold] {record.started_at}\n"
        f"[bold]Duration:[/bold] {record.duration_s:.2f}s\n"
        f"[bold]Tokens:[/bold] {record.input_tokens} in / {record.output_tokens} out\n"
        f"[bold]Cost:[/bold] ${record.cost_usd:.6f}\n"
        f"[bold]Prompt hash:[/bold] [dim]{record.prompt_hash[:16]}…[/dim]",
        title=f"Run Detail  [dim]{record.id[:8]}[/dim]",
        border_style="cyan",
    ))
    console.print("\n[bold]Prompt:[/bold]")
    console.print(record.prompt_text[:2000] + ("…" if len(record.prompt_text) > 2000 else ""))
    console.print("\n[bold]Response:[/bold]")
    console.print(record.response_text[:3000] + ("…" if len(record.response_text) > 3000 else ""))


# ---------------------------------------------------------------------------
# history diff
# ---------------------------------------------------------------------------

@history_group.command("diff")
@click.argument("run_id_a")
@click.argument("run_id_b")
@click.option("--db", "db_path", default=None, type=click.Path())
def history_diff_cmd(run_id_a: str, run_id_b: str, db_path: str | None) -> None:
    """Show unified diff between two run responses.

    \b
    Example:
      promptgenie history diff abc12345 def67890
    """
    import difflib
    from pathlib import Path
    from promptgenie.core.history_db import open_history_db

    with open_history_db(Path(db_path) if db_path else None) as db:
        ra = db.get_run(run_id_a)
        rb = db.get_run(run_id_b)

    if ra is None:
        diag_console.print(f"[red]Error:[/red] Run {run_id_a!r} not found.")
        raise SystemExit(EXIT_USAGE)
    if rb is None:
        diag_console.print(f"[red]Error:[/red] Run {run_id_b!r} not found.")
        raise SystemExit(EXIT_USAGE)

    diff = list(difflib.unified_diff(
        ra.response_text.splitlines(keepends=True),
        rb.response_text.splitlines(keepends=True),
        fromfile=f"run/{run_id_a[:8]}",
        tofile=f"run/{run_id_b[:8]}",
    ))

    if not diff:
        console.print("[green]Responses are identical.[/green]")
        raise SystemExit(EXIT_OK)

    from rich.syntax import Syntax
    console.print(Syntax("".join(diff), "diff", theme="monokai"))


# ---------------------------------------------------------------------------
# history replay
# ---------------------------------------------------------------------------

@history_group.command("replay")
@click.argument("run_id")
@click.option("--provider", default=None, help="Override provider.")
@click.option("--model", default=None, help="Override model.")
@click.option("--dry-run", is_flag=True, help="Show the prompt without sending.")
@click.option("--db", "db_path", default=None, type=click.Path())
def history_replay_cmd(
    run_id: str,
    provider: str | None,
    model: str | None,
    dry_run: bool,
    db_path: str | None,
) -> None:
    """Re-send a historical run's prompt.

    \b
    Example:
      promptgenie history replay abc12345
      promptgenie history replay abc12345 --provider claude --dry-run
    """
    import asyncio
    from pathlib import Path
    from promptgenie.core.history_db import open_history_db

    with open_history_db(Path(db_path) if db_path else None) as db:
        record = db.get_run(run_id)

    if record is None:
        diag_console.print(f"[red]Error:[/red] Run {run_id!r} not found.")
        raise SystemExit(EXIT_USAGE)

    effective_provider = provider or record.provider
    effective_model = model or record.model

    console.print(f"[dim]Replaying run {run_id[:8]} via {effective_provider}/{effective_model}[/dim]")
    console.print(f"\n[bold]Prompt:[/bold]\n{record.prompt_text[:500]}")

    if dry_run:
        console.print("\n[dim]--dry-run: no provider call made.[/dim]")
        raise SystemExit(EXIT_OK)

    try:
        from promptgenie.core.providers import get_provider
        prov = get_provider(effective_provider, model_override=effective_model)
        messages = [{"role": "user", "content": record.prompt_text}]
        response = asyncio.run(prov.complete(
            messages, model=effective_model, max_tokens=1024, timeout=60
        ))
        console.print(f"\n[bold]Response:[/bold]\n{response}")
    except Exception as exc:
        diag_console.print(f"[red]Provider error:[/red] {exc}")
        raise SystemExit(EXIT_FAILURE)


# ---------------------------------------------------------------------------
# history export
# ---------------------------------------------------------------------------

@history_group.command("export")
@click.option("--format", "fmt",
              type=click.Choice(["json", "csv", "ndjson"], case_sensitive=False),
              default="json", show_default=True)
@click.option("--limit", "-n", default=1000, type=int, show_default=True)
@click.option("--out", default=None, help="Write to file instead of stdout.")
@click.option("--db", "db_path", default=None, type=click.Path())
def history_export_cmd(fmt: str, limit: int, out: str | None, db_path: str | None) -> None:
    """Export run history to JSON / CSV / NDJSON.

    \b
    Examples:
      promptgenie history export --format csv > runs.csv
      promptgenie history export --format ndjson --out history.ndjson
    """
    from pathlib import Path
    from promptgenie.core.history_db import open_history_db

    with open_history_db(Path(db_path) if db_path else None) as db:
        content = db.export(fmt=fmt, limit=limit)

    if out:
        Path(out).write_text(content, encoding="utf-8")
        console.print(f"[green]✓[/green] Exported {limit} runs to {out}")
    else:
        sys.stdout.write(content + "\n" if content and not content.endswith("\n") else content)


# ---------------------------------------------------------------------------
# history clear
# ---------------------------------------------------------------------------

@history_group.command("clear")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.option("--db", "db_path", default=None, type=click.Path())
def history_clear_cmd(yes: bool, db_path: str | None) -> None:
    """Delete all run history.

    \b
    Example:
      promptgenie history clear --yes
    """
    from pathlib import Path
    from promptgenie.core.history_db import HistoryDB, open_history_db

    if not yes:
        click.confirm("Delete ALL history? This cannot be undone.", abort=True)

    with open_history_db(Path(db_path) if db_path else None) as db:
        db._conn.execute("DELETE FROM runs")
        db._conn.commit()
        console.print("[green]✓[/green] History cleared.")
