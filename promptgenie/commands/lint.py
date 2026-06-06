import sys
from pathlib import Path

import click
from rich.panel import Panel

from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie.core.formatters import lint_to_json, lint_to_sarif
from promptgenie.core.linter import lint
from promptgenie.renderers.rich import console, format_lint_issues, score_color


def _resolve_config(
    config_path: str | None, no_config: bool
) -> tuple[PromptGenieConfig, str | None]:
    if no_config:
        return PromptGenieConfig(), None
    try:
        from promptgenie.core.config import _find_config

        cfg = load_config(config_path)
        found = config_path or (str(_find_config()) if _find_config() is not None else None)
        return cfg, found
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[yellow]Warning:[/yellow] could not load config: {exc}")
        return PromptGenieConfig(), None


@click.command(name="lint")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.option(
    "--format",
    "output_format",
    default="rich",
    type=click.Choice(["rich", "json", "sarif"]),
    help="Output format (default: rich).",
)
@click.option(
    "--out", "-o", default=None, type=click.Path(), help="Write output to file instead of stdout."
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(),
    help="Path to .promptgenie.yaml config file.",
)
@click.option("--no-config", is_flag=True, help="Ignore .promptgenie.yaml; use default settings.")
def lint_cmd(prompt_file, output_format, out, config_path, no_config):
    """Lint a prompt file for quality and structural issues."""
    cfg, cfg_file = _resolve_config(config_path, no_config)
    text = Path(prompt_file).read_text()
    result = lint(text, config=cfg.linter)

    if output_format == "json":
        output = lint_to_json(result, prompt_path=prompt_file)
        if out:
            Path(out).write_text(output)
        else:
            click.echo(output)
    elif output_format == "sarif":
        output = lint_to_sarif(result, prompt_path=prompt_file)
        if out:
            Path(out).write_text(output)
        else:
            click.echo(output)
    else:
        if cfg_file:
            console.print(f"[dim]Config: {cfg_file}[/dim]")
        color = score_color(result.score)
        console.print(
            Panel(
                format_lint_issues(result),
                title=f"Lint Results  [bold {color}]{result.score}/100[/bold {color}]  [dim]{prompt_file}[/dim]",
                border_style="yellow",
            )
        )
        if out:
            Path(out).write_text(lint_to_json(result, prompt_path=prompt_file))
            console.print(f"[dim]Results saved to {out}[/dim]")

    sys.exit(0 if not result.by_severity("HIGH") else 1)
