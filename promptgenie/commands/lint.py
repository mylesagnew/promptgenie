import sys
from pathlib import Path

import click
from rich.panel import Panel

from promptgenie.core.linter import lint
from promptgenie.core.formatters import lint_to_json, lint_to_sarif
from promptgenie.renderers.rich import console, score_color, format_lint_issues


@click.command(name="lint")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.option("--format", "output_format", default="rich",
              type=click.Choice(["rich", "json", "sarif"]),
              help="Output format (default: rich).")
@click.option("--out", "-o", default=None, type=click.Path(),
              help="Write output to file instead of stdout.")
def lint_cmd(prompt_file, output_format, out):
    """Lint a prompt file for quality and structural issues."""
    text = Path(prompt_file).read_text()
    result = lint(text)

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
        color = score_color(result.score)
        console.print(Panel(
            format_lint_issues(result),
            title=f"Lint Results  [bold {color}]{result.score}/100[/bold {color}]  [dim]{prompt_file}[/dim]",
            border_style="yellow",
        ))
        if out:
            Path(out).write_text(lint_to_json(result, prompt_path=prompt_file))
            console.print(f"[dim]Results saved to {out}[/dim]")

    sys.exit(0 if not result.by_severity("HIGH") else 1)
