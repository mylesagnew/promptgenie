"""template_cmd.py — ``promptgenie template`` command group.

Subcommands
-----------
  template list                list all templates across all layers
  template show <id>           display a template's content
  template edit <id>           open in $EDITOR (user layer copy)
  template new <id>            scaffold a new template interactively
  template validate <id>       check template schema
  template render <id>         dry-run render with optional --var overrides

Examples
--------
  promptgenie template list
  promptgenie template list --category security
  promptgenie template show code-review
  promptgenie template render code-review --var language=Python
  promptgenie template new my-template
  promptgenie template edit my-template
  promptgenie template validate my-template
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys

import click

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.renderers.rich import console, diag_console


@click.group("template", help="Manage prompt templates.")
def template_group() -> None:
    pass


# ---------------------------------------------------------------------------
# template list
# ---------------------------------------------------------------------------


@template_group.command("list")
@click.option("--category", default=None, help="Filter by category.")
@click.option(
    "--layer",
    type=click.Choice(["builtin", "user", "project", "all"], case_sensitive=False),
    default="all",
    show_default=True,
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def template_list_cmd(category: str | None, layer: str, output_format: str) -> None:
    """List all available prompt templates.

    \b
    Examples:
      promptgenie template list
      promptgenie template list --category security
      promptgenie template list --layer user
    """
    from promptgenie.core.template_store import list_all_templates

    templates = list_all_templates()
    if category:
        templates = [t for t in templates if t.category.lower() == category.lower()]
    if layer != "all":
        templates = [t for t in templates if t.source_layer == layer]

    if not templates:
        console.print("[dim]No templates found.[/dim]")
        raise SystemExit(EXIT_OK)

    if output_format == "json":
        import json

        sys.stdout.write(json.dumps([t.to_dict() for t in templates], indent=2) + "\n")
        return

    from rich.table import Table

    table = Table(title="Prompt Templates", show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Category", width=14)
    table.add_column("Layer", width=8)
    table.add_column("Description", style="dim")

    for t in sorted(templates, key=lambda x: (x.category, x.id)):
        table.add_row(t.id, t.name, t.category, t.source_layer, t.description[:60])

    console.print(table)
    console.print(f"\n[dim]{len(templates)} template(s)[/dim]")


# ---------------------------------------------------------------------------
# template show
# ---------------------------------------------------------------------------


@template_group.command("show")
@click.argument("template_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "raw", "json"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def template_show_cmd(template_id: str, output_format: str) -> None:
    """Display a template's content.

    \b
    Examples:
      promptgenie template show code-review
      promptgenie template show code-review --format raw
    """
    from rich.panel import Panel
    from rich.syntax import Syntax

    from promptgenie.core.template_store import resolve_template

    t = resolve_template(template_id)
    if t is None:
        diag_console.print(f"[red]Error:[/red] Template {template_id!r} not found.")
        raise SystemExit(EXIT_USAGE)

    if output_format == "json":
        import json

        sys.stdout.write(json.dumps(t.to_dict(), indent=2) + "\n")
        return

    if output_format == "raw":
        sys.stdout.write(t.prompt + "\n")
        return

    console.print(
        Panel(
            Syntax(t.prompt, "markdown", theme="monokai", word_wrap=True),
            title=f"[bold]{t.name}[/bold]  [dim]{t.id} · {t.category} · {t.source_layer}[/dim]",
            border_style="cyan",
        )
    )
    if t.description:
        console.print(f"[dim]{t.description}[/dim]")
    if t.variables:
        console.print("\n[bold]Variables:[/bold]")
        for v in t.variables:
            req = (
                " [red](required)[/red]" if v.required else f" [dim](default: {v.default!r})[/dim]"
            )
            console.print(f"  {{{{[cyan]{v.name}[/cyan]}}}}  {v.description}{req}")


# ---------------------------------------------------------------------------
# template render
# ---------------------------------------------------------------------------


@template_group.command("render")
@click.argument("template_id")
@click.option(
    "--var",
    "variables",
    multiple=True,
    metavar="KEY=VALUE",
    help="Variable substitutions (repeatable).",
)
@click.option("--out", default=None, help="Write rendered output to file.")
def template_render_cmd(template_id: str, variables: tuple[str, ...], out: str | None) -> None:
    """Render a template with variable substitutions.

    \b
    Examples:
      promptgenie template render code-review --var language=Python --var scope=src/
      promptgenie template render code-review | promptgenie lint -
    """
    from promptgenie.core.template_store import render_template, resolve_template

    t = resolve_template(template_id)
    if t is None:
        diag_console.print(f"[red]Error:[/red] Template {template_id!r} not found.")
        raise SystemExit(EXIT_USAGE)

    var_dict: dict[str, str] = {}
    for v in variables:
        if "=" not in v:
            diag_console.print(f"[red]Error:[/red] --var must be KEY=VALUE, got: {v!r}")
            raise SystemExit(EXIT_USAGE)
        k, val = v.split("=", 1)
        var_dict[k.strip()] = val

    rendered = render_template(t, var_dict)

    if out:
        from pathlib import Path

        Path(out).write_text(rendered, encoding="utf-8")
        console.print(f"[green]✓[/green] Rendered to {out}")
    else:
        sys.stdout.write(rendered + "\n")


# ---------------------------------------------------------------------------
# template validate
# ---------------------------------------------------------------------------


@template_group.command("validate")
@click.argument("template_id")
def template_validate_cmd(template_id: str) -> None:
    """Validate a template's schema and variable references.

    \b
    Example:
      promptgenie template validate my-template
    """
    from promptgenie.core.template_store import resolve_template, validate_template

    t = resolve_template(template_id)
    if t is None:
        diag_console.print(f"[red]Error:[/red] Template {template_id!r} not found.")
        raise SystemExit(EXIT_USAGE)

    errors = validate_template(t)
    if errors:
        console.print(
            f"[red]✗[/red] Template [bold]{template_id}[/bold] has {len(errors)} error(s):"
        )
        for e in errors:
            console.print(f"  [red]•[/red] {e}")
        raise SystemExit(EXIT_FAILURE)
    else:
        console.print(f"[green]✓[/green] Template [bold]{template_id}[/bold] is valid.")
        raise SystemExit(EXIT_OK)


# ---------------------------------------------------------------------------
# template new
# ---------------------------------------------------------------------------


@template_group.command("new")
@click.argument("template_id")
@click.option("--name", default="", help="Human-readable name.")
@click.option("--category", default="", help="Category (e.g. security, quality, code-review).")
@click.option(
    "--layer",
    type=click.Choice(["user", "project"], case_sensitive=False),
    default="user",
    show_default=True,
    help="Where to save the template.",
)
def template_new_cmd(template_id: str, name: str, category: str, layer: str) -> None:
    """Scaffold and save a new template.

    \b
    Examples:
      promptgenie template new my-template --category security
      promptgenie template new my-proj-template --layer project
    """
    from promptgenie.core.template_store import (
        TemplateRecord,
        save_project_template,
        save_user_template,
        validate_template,
    )

    if not name:
        name = click.prompt("Template name")
    if not category:
        category = click.prompt("Category (e.g. security, code-review)", default="general")

    record = TemplateRecord(
        id=template_id,
        name=name,
        category=category,
        description="",
        prompt=(
            "You are a helpful assistant.\n\n## Objective\n{{objective}}\n\n## Scope\n{{scope}}\n"
        ),
        variables=[],
    )

    errors = validate_template(record)
    if errors:
        for e in errors:
            diag_console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(EXIT_USAGE)

    path = save_project_template(record) if layer == "project" else save_user_template(record)

    console.print(f"[green]✓[/green] Template created: [bold]{path}[/bold]")
    console.print(f"[dim]Edit it with: promptgenie template edit {template_id}[/dim]")


# ---------------------------------------------------------------------------
# template edit
# ---------------------------------------------------------------------------


@template_group.command("edit")
@click.argument("template_id")
def template_edit_cmd(template_id: str) -> None:
    """Open a template in $EDITOR (copies to user layer first if built-in).

    \b
    Example:
      promptgenie template edit code-review
      EDITOR=vim promptgenie template edit code-review
    """

    from promptgenie.core.template_store import (
        resolve_template,
        save_user_template,
        validate_template,
    )

    t = resolve_template(template_id)
    if t is None:
        diag_console.print(f"[red]Error:[/red] Template {template_id!r} not found.")
        raise SystemExit(EXIT_USAGE)

    # If built-in, copy to user layer first
    if t.source_layer == "builtin":
        path = save_user_template(t)
        console.print(f"[dim]Copied built-in template to user layer: {path}[/dim]")
    else:
        assert t.source_path is not None
        path = t.source_path

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    ret = subprocess.run([*shlex.split(editor), str(path)]).returncode

    if ret == 0:
        # Re-validate after edit
        t2 = resolve_template(template_id)
        if t2:
            errors = validate_template(t2)
            if errors:
                console.print("[yellow]Warning:[/yellow] Template has validation errors:")
                for e in errors:
                    console.print(f"  [yellow]•[/yellow] {e}")
            else:
                console.print(f"[green]✓[/green] Template {template_id!r} saved and valid.")
