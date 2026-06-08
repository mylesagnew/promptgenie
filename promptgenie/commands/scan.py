import sys

import click
from rich.panel import Panel

from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie.core.fileio import FileTooLargeError, safe_read_text, safe_write_text
from promptgenie.core.formatters import scan_to_json, scan_to_sarif
from promptgenie.core.scanner import scan
from promptgenie.renderers.rich import console, format_scan_findings


def _resolve_config(
    config_path: str | None,
    no_config: bool,
    best_effort: bool = False,
) -> tuple[PromptGenieConfig, str | None]:
    """Load config and return (cfg, config_file_path_or_None).

    Raises ``FileNotFoundError`` / ``ValueError`` when *best_effort* is False and
    the config file cannot be loaded (fail-closed).
    """
    if no_config:
        return PromptGenieConfig(), None
    try:
        from promptgenie.core.config import _find_config

        cfg = load_config(config_path)
        found = config_path or (str(_find_config()) if _find_config() is not None else None)
        return cfg, found
    except (FileNotFoundError, ValueError) as exc:
        if best_effort:
            console.print(f"[yellow]Warning:[/yellow] could not load config: {exc}")
            return PromptGenieConfig(), None
        raise


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
@click.option("--force", is_flag=True, help="Overwrite --out file if it already exists.")
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(),
    help="Path to .promptgenie.yaml config file.",
)
@click.option("--no-config", is_flag=True, help="Ignore .promptgenie.yaml; use default settings.")
@click.option(
    "--best-effort",
    is_flag=True,
    help=(
        "Fall back to default settings when the config file cannot be loaded, "
        "instead of aborting. Without this flag, a bad --config path is a fatal error."
    ),
)
def scan_cmd(prompt_file, output_format, out, force, config_path, no_config, best_effort):
    """Scan a prompt file for security risks."""
    try:
        cfg, cfg_file = _resolve_config(config_path, no_config, best_effort=best_effort)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        console.print("[dim]Use --best-effort to fall back to defaults, or --no-config to skip.[/dim]")
        sys.exit(1)
    try:
        text = safe_read_text(prompt_file)
    except FileTooLargeError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    result = scan(text, config=cfg.scanner)

    if output_format == "json":
        output = scan_to_json(result, prompt_path=prompt_file)
        if out:
            try:
                safe_write_text(out, output, force=force)
            except FileExistsError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)
        else:
            click.echo(output)
    elif output_format == "sarif":
        output = scan_to_sarif(result, prompt_path=prompt_file)
        if out:
            try:
                safe_write_text(out, output, force=force)
            except FileExistsError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)
        else:
            click.echo(output)
    else:
        if cfg_file:
            console.print(f"[dim]Config: {cfg_file}[/dim]")
        if not result.findings:
            console.print(
                Panel(
                    "[green]No heuristic security findings detected.[/green]",
                    title="Prompt Security Scan (heuristic)",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    format_scan_findings(result),
                    title=f"Prompt Security Scan (heuristic)  [bold]Risk: {result.risk_level}[/bold]  [dim]{prompt_file}[/dim]",
                    border_style="red",
                )
            )
        if out:
            try:
                safe_write_text(out, scan_to_json(result, prompt_path=prompt_file), force=force)
                console.print(f"[dim]Results saved to {out}[/dim]")
            except FileExistsError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)
        console.print(
            "[dim]Scanner note: static regex heuristics with Unicode-normalised (NFKC) matching. "
            "Findings indicate risk patterns, not confirmed vulnerabilities. "
            "HIGH/CRITICAL labels reflect pattern severity, not detection certainty — "
            "review each finding before treating it as authoritative. "
            "Does not detect synonym substitution, indirect reference, or multi-turn attacks.[/dim]"
        )

    sys.exit(1 if result.risk_level in ("CRITICAL", "HIGH") else 0)
