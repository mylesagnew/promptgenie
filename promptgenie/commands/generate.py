import sys
from pathlib import Path

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.context_packs import render_pack
from promptgenie.core.generator import generate_prompt
from promptgenie.core.linter import lint
from promptgenie.core.scanner import scan
from promptgenie.renderers.rich import (
    console,
    format_lint_issues,
    format_scan_findings,
    score_color,
)


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
def generate(
    task, target, template, context, output_format, constraints, mode, out, pack, no_lint, no_scan
):
    """Generate an optimized prompt from a rough task description."""
    with console.status("[bold blue]Generating prompt…"):
        if pack:
            try:
                pack_block = render_pack(pack, mode=mode)
                context = (context + "\n\n" + pack_block) if context else pack_block
            except FileNotFoundError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)

        result = generate_prompt(
            task=task,
            target=target,
            template=template,
            context=context,
            output_format=output_format,
            constraints=constraints,
            mode=mode,
        )

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

    if not no_lint:
        lint_result = lint(prompt_text)
        if lint_result.issues:
            console.print(
                Panel(
                    format_lint_issues(lint_result),
                    title=f"Lint  [dim]score {lint_result.score}/100[/dim]",
                    border_style="yellow",
                )
            )

    if not no_scan:
        scan_result = scan(prompt_text)
        if scan_result.findings:
            console.print(
                Panel(
                    format_scan_findings(scan_result),
                    title=f"Security Scan  [dim]risk level: {scan_result.risk_level}[/dim]",
                    border_style="red",
                )
            )

    if out:
        Path(out).write_text(prompt_text)
        console.print(f"\n[green]Prompt saved to {out}[/green]")
