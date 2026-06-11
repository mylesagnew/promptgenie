"""vars.py — ``promptgenie vars`` command group.

Commands
--------
  promptgenie vars inspect <spec>     show resolved variables for a spec
  promptgenie vars list <spec>        list variable names declared in a spec
"""

from __future__ import annotations

import json

import click
import yaml

from promptgenie.core.errors import EXIT_USAGE, PromptGenieError
from promptgenie.core.spec import load_spec
from promptgenie.core.variables import (
    find_variables,
    load_vars_file,
    parse_cli_vars,
)
from promptgenie.renderers.rich import console, diag_console, is_structured_mode


@click.group("vars", help="Inspect and manage PromptSpec variables.")
def vars_group() -> None:
    pass


# ---------------------------------------------------------------------------
# vars list
# ---------------------------------------------------------------------------


@vars_group.command("list")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json", "yaml"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def vars_list_cmd(spec_file: str, output_format: str) -> None:
    """List all variable placeholders declared in a spec's prompt text.

    Example:

      promptgenie vars list my-prompt.yaml

      promptgenie vars list my-prompt.yaml --format json
    """
    try:
        spec = load_spec(spec_file)
    except PromptGenieError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    prompt_text = spec.prompt or ""
    variables = find_variables(prompt_text)
    spec_defaults = spec.vars

    if is_structured_mode(output_format):
        data = {
            "spec_name": spec.name,
            "variables": [
                {
                    "name": v,
                    "has_default": v in spec_defaults,
                    "default": spec_defaults.get(v),
                }
                for v in variables
            ],
            "schema_version": "1.0",
        }
        if output_format == "yaml":
            console.print(yaml.dump(data, default_flow_style=False))
        else:
            console.print(json.dumps(data, indent=2))
        return

    if not variables:
        console.print(f"[dim]No {{{{variable}}}} placeholders found in {spec_file}[/dim]")
        return

    console.print(f"[bold]Variables in {spec_file}[/bold] ([dim]{spec.name}[/dim])")
    for v in variables:
        default = spec_defaults.get(v)
        if default is not None:
            console.print(f"  [cyan]{v}[/cyan]  [dim]default: {default!r}[/dim]")
        else:
            console.print(f"  [cyan]{v}[/cyan]  [red](required)[/red]")


# ---------------------------------------------------------------------------
# vars inspect
# ---------------------------------------------------------------------------


@vars_group.command("inspect")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option(
    "--var",
    "var_list",
    multiple=True,
    metavar="KEY=VALUE",
    help="Inline variable override (repeatable).",
)
@click.option("--vars", "vars_file", default=None, help="YAML/JSON file of variable values.")
@click.option(
    "--env-prefix",
    default="PG_",
    show_default=True,
    help="Environment variable prefix for auto-binding.",
)
@click.option("--redacted", is_flag=True, help="Mask secret variable values in output.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json", "yaml"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def vars_inspect_cmd(
    spec_file: str,
    var_list: tuple[str, ...],
    vars_file: str | None,
    env_prefix: str,
    redacted: bool,
    output_format: str,
) -> None:
    """Inspect how variables in a spec would be resolved.

    Shows the resolved value, source (cli / file / env / default / unresolved),
    and whether the value is a secret.

    \b
    Examples:
      promptgenie vars inspect my-prompt.yaml
      promptgenie vars inspect my-prompt.yaml --var env=prod --redacted
      promptgenie vars inspect my-prompt.yaml --vars prod.yaml --format json
    """
    try:
        spec = load_spec(spec_file)
    except PromptGenieError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    # Merge vars: spec defaults → vars file → CLI vars
    merged: dict = dict(spec.vars)
    if vars_file:
        try:
            merged.update(load_vars_file(vars_file))
        except Exception as exc:
            diag_console.print(f"[red]Failed to load vars file:[/red] {exc}")
            raise SystemExit(EXIT_USAGE) from exc
    cli_var_dict = parse_cli_vars(list(var_list))
    merged.update(cli_var_dict)

    prompt_text = spec.prompt or ""
    variables = find_variables(prompt_text)

    # Determine source per variable
    rows = []
    import os

    for v in variables:
        value = None
        source = "unresolved"
        is_secret = "secret" in v.lower()

        if v in cli_var_dict:
            value = cli_var_dict[v]
            source = "cli"
        elif vars_file and v in (load_vars_file(vars_file) if vars_file else {}):
            value = load_vars_file(vars_file).get(v)
            source = "vars_file"
        else:
            env_key = f"{env_prefix}{v.upper()}"
            env_val = os.environ.get(env_key)
            if env_val is not None:
                value = env_val
                source = f"env:{env_key}"
            elif v in spec.vars:
                value = spec.vars[v]
                source = "spec_default"

        display_value = "***" if (is_secret or redacted) and value is not None else value
        rows.append(
            {
                "name": v,
                "value": display_value,
                "source": source,
                "secret": is_secret,
                "resolved": value is not None,
            }
        )

    if is_structured_mode(output_format):
        data = {
            "spec_name": spec.name,
            "variables": rows,
            "schema_version": "1.0",
        }
        if output_format == "yaml":
            console.print(yaml.dump(data, default_flow_style=False))
        else:
            console.print(json.dumps(data, indent=2))
        return

    if not rows:
        console.print(f"[dim]No variables found in {spec_file}[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Variable resolution: {spec.name}", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Value")
    table.add_column("Source")
    table.add_column("Status")

    for row in rows:
        status = "[green]✓[/green]" if row["resolved"] else "[red]✗ unresolved[/red]"
        secret_tag = " [dim](secret)[/dim]" if row["secret"] else ""
        value_display = str(row["value"]) if row["value"] is not None else "[dim]—[/dim]"
        table.add_row(
            row["name"] + secret_tag,
            value_display,
            str(row["source"]),
            status,
        )
    console.print(table)

    unresolved = [r["name"] for r in rows if not r["resolved"]]
    if unresolved:
        diag_console.print(
            f"\n[yellow]⚠[/yellow] {len(unresolved)} unresolved variable(s): "
            + ", ".join(unresolved)
        )
        raise SystemExit(EXIT_USAGE)
