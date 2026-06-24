"""lock_cmd.py — ``promptgenie lock`` command.

Creates and verifies prompt lockfiles for regulated environments.

Examples
--------
  promptgenie lock prompt.yaml
  promptgenie lock prompt.yaml --out prompt.yaml.lock
  promptgenie lock --check prompt.yaml.lock
  promptgenie lock --check prompt.yaml.lock --strict
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.renderers.rich import console, diag_console


@click.command("lock")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--out", default=None, type=click.Path(),
              help="Custom path for the lockfile (default: <spec>.lock).")
@click.option("--check", is_flag=True,
              help="Verify an existing lockfile rather than creating one.")
@click.option("--strict", is_flag=True,
              help="In --check mode: also fail on missing optional files.")
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json"], case_sensitive=False),
              default="rich", show_default=True)
def lock_cmd(
    spec_file: str,
    out: str | None,
    check: bool,
    strict: bool,
    output_format: str,
) -> None:
    """Create or verify a prompt lockfile.

    A lockfile captures SHA-256 hashes of all inputs (template, policy,
    context files, provider/model) so you can detect drift in regulated
    environments.

    \b
    Examples:
      promptgenie lock prompt.yaml
      promptgenie lock prompt.yaml --out locks/prompt.yaml.lock
      promptgenie lock --check prompt.yaml.lock
    """
    from promptgenie.core.lockfile import (
        check_lockfile,
        create_lockfile,
        load_lockfile,
        write_lockfile,
    )

    if check:
        # --check mode: verify the lockfile
        lock_path = Path(spec_file)  # spec_file is the lockfile path in --check mode
        if not lock_path.exists():
            diag_console.print(f"[red]Error:[/red] Lockfile not found: {lock_path}")
            raise SystemExit(EXIT_USAGE)

        record = load_lockfile(lock_path)
        if record is None:
            diag_console.print(f"[red]Error:[/red] Could not parse lockfile: {lock_path}")
            raise SystemExit(EXIT_USAGE)

        result = check_lockfile(record)
        if output_format == "json":
            import json
            sys.stdout.write(json.dumps({
                "passed": result.passed,
                "stale": result.stale,
                "missing": result.missing,
            }, indent=2) + "\n")
        else:
            if result.passed:
                console.print(f"[green]✓[/green] Lockfile is up to date: [bold]{lock_path}[/bold]")
            else:
                console.print(f"[red]✗[/red] Lockfile is stale: [bold]{lock_path}[/bold]")
                for msg in result.stale:
                    console.print(f"  [red]•[/red] {msg}")
                for msg in result.missing:
                    sev = "[red]•[/red]" if strict else "[yellow]•[/yellow]"
                    console.print(f"  {sev} {msg}")

        if not result.passed or (strict and result.missing):
            raise SystemExit(EXIT_FAILURE)
        raise SystemExit(EXIT_OK)

    # Create mode
    record = create_lockfile(spec_file)
    dest = Path(out) if out else None
    lock_path = write_lockfile(record, dest)

    if output_format == "json":
        import json
        sys.stdout.write(json.dumps(record.to_dict(), indent=2) + "\n")
    else:
        console.print(f"[green]✓[/green] Lockfile created: [bold]{lock_path}[/bold]")
        console.print(f"  Spec hash:    [dim]{record.spec_hash}[/dim]")
        console.print(f"  Locked entries: {len(record.entries)}")
        for e in record.entries:
            if e.kind == "provider":
                console.print(f"  [dim]• provider: {e.id}/{e.model}[/dim]")
            else:
                console.print(f"  [dim]• {e.kind}: {e.path}[/dim]")
