import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text

from promptgenie.core.generator import generate_prompt, list_targets, list_templates
from promptgenie.core.linter import lint
from promptgenie.core.scanner import scan

console = Console()

SEVERITY_COLORS = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan", "INFO": "dim"}
RISK_COLORS = {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan"}
SCORE_COLORS = [(80, "green"), (60, "yellow"), (0, "red")]


def score_color(n: int) -> str:
    for threshold, color in SCORE_COLORS:
        if n >= threshold:
            return color
    return "red"


@click.group()
@click.version_option("1.0.0", prog_name="promptgenie")
def cli():
    """PromptGenie — secure prompt engineering for AI agents and engineering teams."""


@cli.command()
@click.argument("task")
@click.option("--target", "-t", default=None, help="Target AI tool (claude, claude-code, chatgpt, cursor, gemini).")
@click.option("--template", "-T", default=None, help="Prompt template ID (e.g. threat-model, agentic-task).")
@click.option("--context", "-c", default=None, help="Additional context about the task or project.")
@click.option("--output-format", "-f", default=None, help="Desired output format for the generated prompt.")
@click.option("--constraints", "-x", default=None, help="Constraints or forbidden actions.")
@click.option("--mode", "-m", default="standard", type=click.Choice(["minimal", "standard", "exhaustive"]),
              help="Prompt verbosity mode.")
@click.option("--out", "-o", default=None, type=click.Path(), help="Save generated prompt to file.")
@click.option("--no-lint", is_flag=True, help="Skip automatic lint pass.")
@click.option("--no-scan", is_flag=True, help="Skip automatic security scan.")
def generate(task, target, template, context, output_format, constraints, mode, out, no_lint, no_scan):
    """Generate an optimized prompt from a rough task description."""
    with console.status("[bold blue]Generating prompt…"):
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
    console.print(Panel(
        prompt_text,
        title=f"[bold]Generated Prompt[/bold]  [dim]target:[/dim] {result['target']}  [dim]template:[/dim] {result['template']}  [dim]mode:[/dim] {mode}",
        border_style="blue",
    ))

    # Score summary
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

    # Inline lint
    if not no_lint:
        lint_result = lint(prompt_text)
        if lint_result.issues:
            console.print(Panel(
                _format_lint_issues(lint_result),
                title=f"Lint  [dim]score {lint_result.score}/100[/dim]",
                border_style="yellow",
            ))

    # Inline security scan
    if not no_scan:
        scan_result = scan(prompt_text)
        if scan_result.findings:
            console.print(Panel(
                _format_scan_findings(scan_result),
                title=f"Security Scan  [dim]risk level: {scan_result.risk_level}[/dim]",
                border_style="red",
            ))

    if out:
        Path(out).write_text(prompt_text)
        console.print(f"\n[green]Prompt saved to {out}[/green]")


@cli.command(name="lint")
@click.argument("prompt_file", type=click.Path(exists=True))
def lintcmd(prompt_file):
    """Lint a prompt file for quality and structural issues."""
    text = Path(prompt_file).read_text()
    result = lint(text)

    color = score_color(result.score)
    console.print(Panel(
        _format_lint_issues(result),
        title=f"Lint Results  [bold {color}]{result.score}/100[/bold {color}]  [dim]{prompt_file}[/dim]",
        border_style="yellow",
    ))

    sys.exit(0 if not result.by_severity("HIGH") else 1)


@cli.command(name="scan")
@click.argument("prompt_file", type=click.Path(exists=True))
def scan_cmd(prompt_file):
    """Scan a prompt file for security risks."""
    text = Path(prompt_file).read_text()
    result = scan(text)

    if not result.findings:
        console.print(Panel("[green]No security findings.[/green]", title="Security Scan", border_style="green"))
        sys.exit(0)

    console.print(Panel(
        _format_scan_findings(result),
        title=f"Security Scan  [bold]Risk: {result.risk_level}[/bold]  [dim]{prompt_file}[/dim]",
        border_style="red",
    ))

    sys.exit(1 if result.risk_level in ("CRITICAL", "HIGH") else 0)


@cli.command("list-targets")
def list_targets_cmd():
    """List all available target AI tool profiles."""
    targets = list_targets()
    table = Table(title="Available Target Profiles", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Category", style="dim")
    table.add_column("Strengths", style="dim")
    for t in targets:
        strengths = ", ".join(t["strengths"][:3])
        table.add_row(t["id"], t["name"], t["category"], strengths)
    console.print(table)


@cli.command("list-templates")
def list_templates_cmd():
    """List all available prompt templates."""
    templates = list_templates()
    table = Table(title="Available Templates", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Category", style="dim")
    table.add_column("Description", style="dim")
    for t in templates:
        table.add_row(t["id"], t["name"], t["category"], t["description"])
    console.print(table)


def _format_lint_issues(result) -> str:
    if not result.issues:
        return "[green]No issues found.[/green]"
    lines = []
    for issue in result.issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lines.append(f"[{color}][{issue.severity}][/{color}] [{issue.code}] {issue.message}")
        if issue.suggestion:
            lines.append(f"  [dim]→ {issue.suggestion}[/dim]")
    return "\n".join(lines)


def _format_scan_findings(result) -> str:
    if not result.findings:
        return "[green]No findings.[/green]"
    lines = []
    for f in result.findings:
        color = RISK_COLORS.get(f.risk, "white")
        lines.append(f"[{color}][{f.risk}][/{color}] [{f.code}] {f.message}")
        if f.recommendation:
            lines.append(f"  [dim]→ {f.recommendation}[/dim]")
    return "\n".join(lines)


if __name__ == "__main__":
    cli()
