import sys
from pathlib import Path

import click
from rich.panel import Panel

from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie.core.formatters import scan_to_json, scan_to_sarif
from promptgenie.core.scanner import scan
from promptgenie.renderers.rich import console, format_scan_findings


def _resolve_config(
    config_path: str | None, no_config: bool
) -> tuple[PromptGenieConfig, str | None]:
    """Load config and return (cfg, config_file_path_or_None)."""
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


@click.command(name="scan")
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
def scan_cmd(prompt_file, output_format, out, config_path, no_config):
    """Scan a prompt file for security risks."""
    cfg, cfg_file = _resolve_config(config_path, no_config)
    text = Path(prompt_file).read_text()
    result = scan(text, config=cfg.scanner)

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
        if cfg_file:
            console.print(f"[dim]Config: {cfg_file}[/dim]")
        if not result.findings:
            console.print(
                Panel(
                    "[green]No security findings.[/green]",
                    title="Security Scan",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    format_scan_findings(result),
                    title=f"Security Scan  [bold]Risk: {result.risk_level}[/bold]  [dim]{prompt_file}[/dim]",
                    border_style="red",
                )
            )
        if out:
            Path(out).write_text(scan_to_json(result, prompt_path=prompt_file))
            console.print(f"[dim]Results saved to {out}[/dim]")
        console.print(
            "[dim]Scanner note: static regex + Unicode-normalised matching. "
            "Does not detect synonym substitution, indirect reference, or multi-turn attacks.[/dim]"
        )

    sys.exit(1 if result.risk_level in ("CRITICAL", "HIGH") else 0)
