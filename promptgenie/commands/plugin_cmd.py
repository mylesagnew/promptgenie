"""plugin_cmd.py — ``promptgenie plugin`` command group.

Subcommands
-----------
  plugin list      list installed plugins across all entry-point groups
  plugin doctor    check compatibility of all installed plugins
  plugin scaffold  generate a stub plugin file
  plugin install   thin wrapper around pip install (for discoverability)

Examples
--------
  promptgenie plugin list
  promptgenie plugin list --group promptgenie.providers
  promptgenie plugin doctor
  promptgenie plugin scaffold my-checker --group promptgenie.rules
  promptgenie plugin install my-pg-plugin
"""

from __future__ import annotations

import subprocess
import sys

import click

from promptgenie.core.plugin import (
    PLUGIN_GROUPS,
    check_plugin_compat,
    list_plugins,
    scaffold_plugin,
)
from promptgenie.renderers.rich import console


@click.group("plugin", help="Manage PromptGenie plugins.")
def plugin_group() -> None:
    pass


# ---------------------------------------------------------------------------
# plugin list
# ---------------------------------------------------------------------------


@plugin_group.command("list")
@click.option(
    "--group",
    "filter_group",
    default=None,
    type=click.Choice(list(PLUGIN_GROUPS), case_sensitive=False),
    help="Filter by entry-point group.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def plugin_list_cmd(filter_group: str | None, output_format: str) -> None:
    """List all installed PromptGenie plugins.

    \b
    Examples:
      promptgenie plugin list
      promptgenie plugin list --group promptgenie.providers
      promptgenie plugin list --format json
    """
    from promptgenie.core.errors import EXIT_OK

    groups = (filter_group,) if filter_group else None
    plugins = list_plugins(groups)

    if not plugins:
        console.print("[dim]No plugins installed.[/dim]")
        console.print("[dim]Install a plugin with: [bold]pip install <plugin-package>[/bold][/dim]")
        raise SystemExit(EXIT_OK)

    if output_format == "json":
        import json
        import sys

        data = [
            {
                "name": p.name,
                "group": p.group,
                "package": p.package,
                "version": p.version,
                "origin": p.origin,
                "entry_point": p.entry_point,
            }
            for p in plugins
        ]
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return

    from rich.table import Table

    table = Table(title="Installed Plugins", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Package", no_wrap=True)
    table.add_column("Version", width=9)
    table.add_column("Origin", width=8)
    table.add_column("Entry Point", style="dim")

    for p in sorted(plugins, key=lambda x: (x.group, x.name)):
        table.add_row(
            p.name,
            p.group_label,
            p.package,
            p.version,
            p.origin,
            p.entry_point,
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(plugins)} plugin(s)[/dim]")


# ---------------------------------------------------------------------------
# plugin doctor
# ---------------------------------------------------------------------------


@plugin_group.command("doctor")
@click.option(
    "--group",
    "filter_group",
    default=None,
    type=click.Choice(list(PLUGIN_GROUPS), case_sensitive=False),
)
def plugin_doctor_cmd(filter_group: str | None) -> None:
    """Check compatibility of all installed plugins.

    \b
    Example:
      promptgenie plugin doctor
    """
    from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK

    groups = (filter_group,) if filter_group else None
    plugins = list_plugins(groups)

    if not plugins:
        console.print("[dim]No plugins installed.[/dim]")
        raise SystemExit(EXIT_OK)

    any_issue = False
    for p in sorted(plugins, key=lambda x: (x.group, x.name)):
        warnings = check_plugin_compat(p)
        if warnings:
            any_issue = True
            console.print(f"[red]✗[/red] [bold]{p.name}[/bold] ({p.group_label}) v{p.version}")
            for w in warnings:
                console.print(f"  [yellow]⚠[/yellow] {w}")
        else:
            console.print(f"[green]✓[/green] [bold]{p.name}[/bold] ({p.group_label}) v{p.version}")

    raise SystemExit(EXIT_FAILURE if any_issue else EXIT_OK)


# ---------------------------------------------------------------------------
# plugin scaffold
# ---------------------------------------------------------------------------


@plugin_group.command("scaffold")
@click.argument("name")
@click.option(
    "--group",
    "group",
    type=click.Choice(list(PLUGIN_GROUPS), case_sensitive=False),
    required=True,
    help="Entry-point group for the new plugin.",
)
@click.option(
    "--out", "out_dir", default=".", show_default=True, help="Directory to write the stub file."
)
def plugin_scaffold_cmd(name: str, group: str, out_dir: str) -> None:
    """Generate a stub plugin file.

    \b
    Examples:
      promptgenie plugin scaffold my-rules --group promptgenie.rules
      promptgenie plugin scaffold my-provider --group promptgenie.providers --out src/
    """
    from promptgenie.core.errors import EXIT_OK

    path = scaffold_plugin(name, group, output_dir=out_dir)
    console.print(f"[green]✓[/green] Plugin stub created: [bold]{path}[/bold]")
    console.print(
        f'[dim]Register it in pyproject.toml under [project.entry-points."{group}"][/dim]'
    )
    raise SystemExit(EXIT_OK)


# ---------------------------------------------------------------------------
# plugin install
# ---------------------------------------------------------------------------


@plugin_group.command("install")
@click.argument("packages", nargs=-1, required=True)
@click.option("--upgrade", "-U", is_flag=True, help="Upgrade the package if already installed.")
def plugin_install_cmd(packages: tuple[str, ...], upgrade: bool) -> None:
    """Install a plugin package via pip.

    \b
    Example:
      promptgenie plugin install promptgenie-myplugin
      promptgenie plugin install ./local-plugin/ --upgrade
    """
    cmd = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd.extend(packages)
    result = subprocess.run(cmd)
    if result.returncode == 0:
        console.print(
            f"[green]✓[/green] Installed: {', '.join(packages)}. "
            "Run [bold]promptgenie plugin list[/bold] to verify."
        )
    raise SystemExit(result.returncode)
