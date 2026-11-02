"""spec.py — CLI commands for PromptSpec lifecycle management.

Commands
--------
  promptgenie spec init <name>         scaffold a new spec file
  promptgenie spec render <file>       render prompt with resolved variables (no provider call)
  promptgenie spec validate <file>     validate spec structure against JSON schema
  promptgenie spec schema              print the JSON Schema for PromptSpec
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import yaml

from promptgenie.core.errors import EXIT_USAGE, PromptGenieError
from promptgenie.core.spec import (
    SPEC_SCHEMA_PATH,
    load_spec,
    spec_init_template,
    validate_spec,
)
from promptgenie.core.variables import load_vars_file, parse_cli_vars
from promptgenie.renderers import rich as renderer
from promptgenie.renderers.rich import is_structured_mode


@click.group("spec", help="Manage PromptSpec files.")
def spec_group() -> None:
    pass


# ---------------------------------------------------------------------------
# spec init
# ---------------------------------------------------------------------------


@spec_group.command("init")
@click.argument("name")
@click.option(
    "--target",
    "-t",
    default="claude-code",
    show_default=True,
    help="Target profile name (e.g. claude-code, chatgpt, ollama).",
)
@click.option(
    "--out", "-o", default=None, help="Output file path. Default: <name>.prompt.yaml in cwd."
)
@click.option("--force", is_flag=True, help="Overwrite if file already exists.")
def spec_init_cmd(name: str, target: str, out: str | None, force: bool) -> None:
    """Scaffold a new PromptSpec YAML file at <name>.prompt.yaml.

    Example:

      promptgenie spec init code-review --target claude-code

      promptgenie spec init deploy-check --target ollama --out specs/deploy.yaml
    """
    output_path = Path(out) if out else Path(f"{name.replace(' ', '-')}.prompt.yaml")
    if output_path.exists() and not force:
        renderer.diag_console.print(
            f"[yellow]File already exists:[/yellow] {output_path}\nUse --force to overwrite."
        )
        raise SystemExit(EXIT_USAGE)

    content = spec_init_template(name=name, target=target)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    renderer.console.print(f"[green]✓[/green] Created spec: [bold]{output_path}[/bold]")
    renderer.console.print(f"  Edit it, then run: [bold]promptgenie run {output_path}[/bold]")


# ---------------------------------------------------------------------------
# spec validate
# ---------------------------------------------------------------------------


@spec_group.command("validate")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option(
    "--format",
    "output_format",
    default="rich",
    type=click.Choice(["rich", "json"], case_sensitive=False),
    help="Output format.",
)
def spec_validate_cmd(spec_file: str, output_format: str) -> None:
    """Validate a PromptSpec file against the schema.

    Exits 0 if valid, 2 if invalid.

    Example:

      promptgenie spec validate my-prompt.yaml

      promptgenie spec validate my-prompt.yaml --format json
    """
    structured = is_structured_mode(output_format)
    try:
        spec = load_spec(spec_file)
    except PromptGenieError as exc:
        if structured:
            renderer.console.print(
                json.dumps(
                    {
                        "valid": False,
                        "file": spec_file,
                        "errors": [str(exc)],
                        "schema_version": "1.0",
                    }
                )
            )
        else:
            renderer.diag_console.print(f"[red]✗[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    errors = validate_spec(spec)
    if structured:
        renderer.console.print(
            json.dumps(
                {
                    "valid": len(errors) == 0,
                    "file": spec_file,
                    "errors": errors,
                    "schema_version": "1.0",
                }
            )
        )
    else:
        if errors:
            renderer.diag_console.print(f"[red]✗[/red] [bold]{spec_file}[/bold] is invalid:")
            for err in errors:
                renderer.diag_console.print(f"  • {err}")
            raise SystemExit(EXIT_USAGE)
        else:
            renderer.console.print(
                f"[green]✓[/green] [bold]{spec_file}[/bold] is valid ([dim]{spec.name}[/dim])"
            )


# ---------------------------------------------------------------------------
# spec render
# ---------------------------------------------------------------------------


@spec_group.command("render")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option(
    "--var",
    "var_list",
    multiple=True,
    metavar="KEY=VALUE",
    help="Inline variable override (repeatable).",
)
@click.option("--vars", "vars_file", default=None, help="YAML/JSON file of variable values.")
@click.option("--no-input", is_flag=True, help="Fail instead of prompting for missing variables.")
@click.option(
    "--format",
    "output_format",
    default="text",
    type=click.Choice(["text", "json"], case_sensitive=False),
    help="Output format.",
)
@click.option("--show-context", is_flag=True, help="Include assembled context in output.")
@click.option(
    "--trust",
    "trust_spec",
    is_flag=True,
    help="Trust this spec's host-touching context sources (needed with --show-context).",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Assume yes to the trust prompt.")
def spec_render_cmd(
    spec_file: str,
    var_list: tuple[str, ...],
    vars_file: str | None,
    no_input: bool,
    output_format: str,
    show_context: bool,
    trust_spec: bool,
    assume_yes: bool,
) -> None:
    """Render a PromptSpec — resolve variables and assemble the prompt without calling a provider.

    Useful for inspecting what will be sent before running.

    Example:

      promptgenie spec render my-prompt.yaml --var env=prod

      promptgenie spec render my-prompt.yaml --format json | jq .prompt
    """
    from promptgenie.core.context_builder import build_context
    from promptgenie.core.variables import resolve_variables

    try:
        spec = load_spec(spec_file)
    except PromptGenieError as exc:
        renderer.diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    # Merge vars
    merged: dict = dict(spec.vars)
    if vars_file:
        merged.update(load_vars_file(vars_file))
    cli_var_dict = parse_cli_vars(list(var_list))
    merged.update(cli_var_dict)

    prompt_text = spec.prompt or ""
    try:
        rendered, resolved = resolve_variables(
            prompt_text,
            cli_vars=cli_var_dict,
            vars_file_values=merged,
            no_input=no_input,
        )
    except Exception as exc:
        renderer.diag_console.print(f"[red]Variable error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    # Context
    context_text = ""
    if show_context and spec.context:
        # Gathering context runs the spec's cmd/file/glob/env sources on the host,
        # so it needs the same trust decision as `promptgenie run` (S-2 / T1).
        from promptgenie.commands.run import _trust_gate

        _trust_gate(
            spec=spec,
            spec_file=spec_file,
            no_input=no_input,
            trust_spec=trust_spec,
            assume_yes=assume_yes,
        )
        base_dir = Path(spec_file).parent
        manifest = build_context(spec.context, base_dir=base_dir)
        context_text = manifest.text

    if output_format == "json":
        output = {
            "spec_name": spec.name,
            "target": spec.target,
            "prompt": rendered,
            "resolved_vars": {
                k: ("***" if "secret" in k.lower() else v) for k, v in resolved.items()
            },
            "schema_version": "1.0",
        }
        if show_context:
            output["context"] = context_text
        renderer.console.print(json.dumps(output, indent=2))
    else:
        if context_text:
            renderer.console.print("─" * 60)
            renderer.console.print("[bold]Context[/bold]")
            renderer.console.print(context_text)
            renderer.console.print("─" * 60)
        renderer.console.print(rendered)


# ---------------------------------------------------------------------------
# spec schema
# ---------------------------------------------------------------------------


@spec_group.command("schema")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "yaml"], case_sensitive=False),
    help="Output format.",
)
def spec_schema_cmd(output_format: str) -> None:
    """Print the JSON Schema for PromptSpec.

    Example:

      promptgenie spec schema | jq '.properties.target'

      promptgenie spec schema --format yaml
    """
    import json

    schema_text = SPEC_SCHEMA_PATH.read_text(encoding="utf-8")
    schema_obj = json.loads(schema_text)
    if output_format == "yaml":
        renderer.console.print(yaml.dump(schema_obj, default_flow_style=False, sort_keys=False))
    else:
        renderer.console.print(schema_text)
