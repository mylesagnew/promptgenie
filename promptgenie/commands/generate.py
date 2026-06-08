import sys

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie.core.context_packs import render_pack
from promptgenie.core.fileio import safe_write_text
from promptgenie.core.generator import generate_prompt
from promptgenie.core.linter import lint
from promptgenie.core.scanner import scan
from promptgenie.renderers.rich import (
    console,
    format_lint_issues,
    format_scan_findings,
    score_color,
)


def _resolve_config(
    config_path: str | None,
    no_config: bool,
    best_effort: bool = False,
) -> tuple[PromptGenieConfig, str | None]:
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
        # Fail-closed: re-raise so the caller can exit with a clear message
        raise


@click.command()
@click.argument("task")
@click.option(
    "--target",
    "-t",
    default=None,
    help="Target AI tool (claude, claude-code, chatgpt, cursor, gemini).",
)
@click.option(
    "--template", "-T", default=None, help="Prompt template ID (e.g. threat-model, agentic-task)."
)
@click.option("--context", "-c", default=None, help="Additional context about the task or project.")
@click.option(
    "--output-format", "-f", default=None, help="Desired output format for the generated prompt."
)
@click.option("--constraints", "-x", default=None, help="Constraints or forbidden actions.")
@click.option(
    "--mode",
    "-m",
    default="standard",
    type=click.Choice(["minimal", "standard", "exhaustive"]),
    help="Prompt verbosity mode.",
)
@click.option("--out", "-o", default=None, type=click.Path(), help="Save generated prompt to file.")
@click.option(
    "--pack", "-p", default=None, help="Context pack ID to inject (e.g. react-supabase-app)."
)
@click.option("--no-lint", is_flag=True, help="Skip automatic lint pass.")
@click.option("--no-scan", is_flag=True, help="Skip automatic security scan.")
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
        "Fall back to built-in defaults when a profile, template, or config file is missing "
        "instead of aborting with an error. Useful for pipelines where partial output is "
        "acceptable. Without this flag, unknown --target or --template values are fatal errors."
    ),
)
def generate(
    task,
    target,
    template,
    context,
    output_format,
    constraints,
    mode,
    out,
    pack,
    no_lint,
    no_scan,
    force,
    config_path,
    no_config,
    best_effort,
):
    """Generate an optimized prompt from a rough task description."""
    try:
        cfg, cfg_file = _resolve_config(config_path, no_config, best_effort=best_effort)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        console.print("[dim]Use --best-effort to fall back to defaults, or --no-config to skip.[/dim]")
        sys.exit(1)

    with console.status("[bold blue]Generating prompt…"):
        if pack:
            try:
                pack_block = render_pack(pack, mode=mode)
                context = (context + "\n\n" + pack_block) if context else pack_block
            except FileNotFoundError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)

        try:
            result = generate_prompt(
                task=task,
                target=target,
                template=template,
                context=context,
                output_format=output_format,
                constraints=constraints,
                mode=mode,
                best_effort=best_effort,
            )
        except FileNotFoundError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            console.print("[dim]Use --best-effort to fall back to built-in defaults.[/dim]")
            sys.exit(1)

    prompt_text = result["prompt"]
    score = result["score"]
    tokens = result["token_estimate"]

    console.print()
    console.print(
        Panel(
            prompt_text,
            title=(
                f"[bold]Generated Prompt[/bold]  [dim]target:[/dim] {result['target']}"
                f"  [dim]template:[/dim] {result['template']}  [dim]mode:[/dim] {mode}"
            ),
            border_style="blue",
        )
    )

    total = score["total"]
    color = score_color(total)
    score_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    score_table.add_column("Metric", style="dim")
    score_table.add_column("Score", justify="right")
    for k, v in score["breakdown"].items():
        score_table.add_row(k.replace("_", " ").title(), f"[{score_color(v)}]{v}[/]")
    score_table.add_row("", "")
    score_table.add_row("[bold]Overall[/bold]", f"[{color} bold]{total}/100[/]")
    score_table.add_row("[dim]Token estimate[/dim]", f"[dim]{tokens:,}[/dim]")
    console.print(Panel(score_table, title="Prompt Quality Score", border_style="dim"))

    if cfg_file:
        console.print(f"[dim]Config: {cfg_file}[/dim]")

    if not no_lint:
        lint_result = lint(prompt_text, config=cfg.linter)
        if lint_result.issues:
            console.print(
                Panel(
                    format_lint_issues(lint_result),
                    title=f"Lint  [dim]score {lint_result.score}/100[/dim]",
                    border_style="yellow",
                )
            )

    if not no_scan:
        scan_result = scan(prompt_text, config=cfg.scanner)
        if scan_result.findings:
            console.print(
                Panel(
                    format_scan_findings(scan_result),
                    title=f"Security Scan  [dim]risk level: {scan_result.risk_level}[/dim]",
                    border_style="red",
                )
            )

    if out:
        try:
            safe_write_text(out, prompt_text, force=force)
            console.print(f"\n[green]Prompt saved to {out}[/green]")
        except FileExistsError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
