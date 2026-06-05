import sys
from pathlib import Path

import click
from rich.panel import Panel

from promptgenie.core.scanner import scan
from promptgenie.core.formatters import scan_to_json, scan_to_sarif
from promptgenie.renderers.rich import console, format_scan_findings


@click.command(name="scan")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.option("--format", "output_format", default="rich",
              type=click.Choice(["rich", "json", "sarif"]),
              help="Output format (default: rich).")
@click.option("--out", "-o", default=None, type=click.Path(),
              help="Write output to file instead of stdout.")
def scan_cmd(prompt_file, output_format, out):
    """Scan a prompt file for security risks."""
    text = Path(prompt_file).read_text()
    result = scan(text)

    if output_format == "json":
        output = scan_to_json(result, prompt_path=prompt_file)
        if out:
            Path(out).write_text(output)
        else:
            click.echo(output)
    elif output_format == "sarif":
        output = scan_to_sarif(result, prompt_path=prompt_file)
        if out:
            Path(out).write_text(output)
        else:
            click.echo(output)
    else:
        if not result.findings:
            console.print(Panel("[green]No security findings.[/green]", title="Security Scan", border_style="green"))
        else:
            console.print(Panel(
                format_scan_findings(result),
                title=f"Security Scan  [bold]Risk: {result.risk_level}[/bold]  [dim]{prompt_file}[/dim]",
                border_style="red",
            ))
        if out:
            Path(out).write_text(scan_to_json(result, prompt_path=prompt_file))
            console.print(f"[dim]Results saved to {out}[/dim]")

    sys.exit(1 if result.risk_level in ("CRITICAL", "HIGH") else 0)
