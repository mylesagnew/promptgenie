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
from promptgenie.core.differ import diff_prompts
from promptgenie.core.adapter import adapt

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


@cli.command(name="adapt")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.option("--from", "from_target", required=True, help="Source target profile (e.g. claude-code).")
@click.option("--to", "to_target", required=True, help="Destination target profile (e.g. cursor).")
@click.option("--out", "-o", default=None, type=click.Path(), help="Save adapted prompt to file.")
@click.option("--show-original", is_flag=True, help="Print original prompt alongside adapted version.")
def adapt_cmd(prompt_file, from_target, to_target, out, show_original):
    """Translate a prompt from one target profile to another."""
    with console.status("[bold blue]Adapting prompt…"):
        result = adapt(prompt_file, from_target, to_target)

    from_name = result.source_target
    to_name = result.dest_target
    console.print()

    # ── Original (optional) ──────────────────────────────────────────────────
    if show_original:
        console.print(Panel(
            result.original_text,
            title=f"[dim]Original — {from_name}[/dim]",
            border_style="dim",
        ))

    # ── Adapted prompt ───────────────────────────────────────────────────────
    console.print(Panel(
        result.adapted_text,
        title=f"[bold]Adapted Prompt[/bold]  [dim]{from_name}[/dim] → [cyan]{to_name}[/cyan]",
        border_style="blue",
    ))

    # ── Change log ───────────────────────────────────────────────────────────
    ACTION_STYLE = {
        "kept":      ("dim",    "KEPT"),
        "rewritten": ("yellow", "REWRITTEN"),
        "added":     ("green",  "ADDED"),
        "dropped":   ("red",    "DROPPED"),
    }
    change_lines = []
    for change in result.changes:
        if change.name == "":
            continue
        color, label = ACTION_STYLE.get(change.action, ("white", change.action.upper()))
        change_lines.append(f"[{color}][{label}][/{color}]  {change.name}")
        change_lines.append(f"  [dim]{change.reason}[/dim]")

    console.print(Panel("\n".join(change_lines), title="Change Log", border_style="dim"))

    # ── Score & token summary ────────────────────────────────────────────────
    summary = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    summary.add_column("Metric", style="dim")
    summary.add_column(f"Original ({from_name})", justify="right")
    summary.add_column(f"Adapted ({to_name})", justify="right")

    def _delta(a: int, b: int, invert: bool = False) -> str:
        d = b - a
        color = "green" if (d > 0 and not invert) or (d < 0 and invert) else ("red" if d != 0 else "dim")
        prefix = "+" if d > 0 else ""
        return f"[{color}]{prefix}{d}[/{color}]"

    summary.add_row("Tokens", str(result.source_tokens), str(result.adapted_tokens) + f"  {_delta(result.source_tokens, result.adapted_tokens, invert=True)}")
    summary.add_row("Quality score", f"{result.source_score['total']}/100", f"{result.adapted_score['total']}/100  {_delta(result.source_score['total'], result.adapted_score['total'])}")
    console.print(Panel(summary, title="Score & Token Summary", border_style="dim"))

    # ── Warnings ─────────────────────────────────────────────────────────────
    if result.warnings:
        warn_lines = "\n".join(f"[yellow]⚠[/yellow]  {w}" for w in result.warnings)
        console.print(Panel(warn_lines, title="Warnings", border_style="yellow"))

    # ── Save ─────────────────────────────────────────────────────────────────
    if out:
        from pathlib import Path as _Path
        _Path(out).write_text(result.adapted_text)
        console.print(f"\n[green]Adapted prompt saved to {out}[/green]")


@cli.command(name="diff")
@click.argument("prompt_a", type=click.Path(exists=True))
@click.argument("prompt_b", type=click.Path(exists=True))
@click.option("--target", "-t", default="claude", help="Target profile to use for scoring.")
@click.option("--unified", "-u", is_flag=True, help="Show full unified diff.")
def diff_cmd(prompt_a, prompt_b, target, unified):
    """Compare two prompt versions — token delta, risk delta, quality delta, section changes."""
    with console.status("[bold blue]Diffing prompts…"):
        result = diff_prompts(prompt_a, prompt_b, target=target)

    # ── Header ──────────────────────────────────────────────────────────────
    console.print()
    console.print(f"[bold]Comparing[/bold]  [cyan]{prompt_a}[/cyan]  →  [cyan]{prompt_b}[/cyan]\n")

    # ── Summary table ────────────────────────────────────────────────────────
    summary = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    summary.add_column("Metric", style="dim")
    summary.add_column("Version A", justify="right")
    summary.add_column("Version B", justify="right")
    summary.add_column("Delta", justify="right")

    def _delta_str(n: int, invert: bool = False) -> str:
        good = n <= 0 if invert else n >= 0
        color = "green" if (n > 0 and not invert) or (n < 0 and invert) else ("red" if n != 0 else "dim")
        prefix = "+" if n > 0 else ""
        return f"[{color}]{prefix}{n}[/{color}]"

    summary.add_row(
        "Tokens",
        str(result.a_tokens),
        str(result.b_tokens),
        _delta_str(result.token_delta, invert=True),
    )
    summary.add_row(
        "Quality score",
        f"{result.a_score['total']}/100",
        f"{result.b_score['total']}/100",
        _delta_str(result.score_delta),
    )
    summary.add_row(
        "Lint issues",
        str(len(result.a_lint.issues)),
        str(len(result.b_lint.issues)),
        _delta_str(result.lint_delta, invert=True),
    )
    summary.add_row(
        "Security findings",
        str(len(result.a_scan.findings)),
        str(len(result.b_scan.findings)),
        _delta_str(len(result.b_scan.findings) - len(result.a_scan.findings), invert=True),
    )
    console.print(Panel(summary, title="Summary", border_style="blue"))

    # ── Score breakdown ───────────────────────────────────────────────────────
    score_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    score_table.add_column("Dimension", style="dim")
    score_table.add_column("A", justify="right")
    score_table.add_column("B", justify="right")
    score_table.add_column("Δ", justify="right")
    for dim, a_val in result.a_score["breakdown"].items():
        b_val = result.b_score["breakdown"].get(dim, 0)
        delta = b_val - a_val
        score_table.add_row(
            dim.replace("_", " ").title(),
            f"[{score_color(a_val)}]{a_val}[/]",
            f"[{score_color(b_val)}]{b_val}[/]",
            _delta_str(delta),
        )
    console.print(Panel(score_table, title="Quality Score Breakdown", border_style="dim"))

    # ── Section changes ───────────────────────────────────────────────────────
    STATUS_STYLE = {
        "added":     ("green",  "ADDED"),
        "removed":   ("red",    "REMOVED"),
        "changed":   ("yellow", "CHANGED"),
        "unchanged": ("dim",    "UNCHANGED"),
    }
    section_lines = []
    for delta in result.section_deltas:
        color, label = STATUS_STYLE[delta.status]
        if delta.name == "__preamble__":
            continue
        section_lines.append(f"[{color}][{label}][/{color}]  {delta.name}")
        if delta.status == "changed":
            inline = list(__import__("difflib").unified_diff(
                delta.a_lines, delta.b_lines, lineterm="", n=1
            ))
            for line in inline[2:]:  # skip @@/--- headers
                if line.startswith("+"):
                    section_lines.append(f"  [green]{line}[/green]")
                elif line.startswith("-"):
                    section_lines.append(f"  [red]{line}[/red]")

    if section_lines:
        console.print(Panel("\n".join(section_lines), title="Section Changes", border_style="dim"))

    # ── Lint delta ────────────────────────────────────────────────────────────
    lint_lines = []
    for issue in result.resolved_lint_issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lint_lines.append(f"[green][RESOLVED][/green] [{color}]{issue.severity}[/{color}] [{issue.code}] {issue.message}")
    for issue in result.new_lint_issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lint_lines.append(f"[red][NEW][/red]      [{color}]{issue.severity}[/{color}] [{issue.code}] {issue.message}")
    if lint_lines:
        console.print(Panel("\n".join(lint_lines), title="Lint Changes", border_style="yellow"))

    # ── Security delta ────────────────────────────────────────────────────────
    sec_lines = []
    for f in result.resolved_security_findings:
        color = RISK_COLORS.get(f.risk, "white")
        sec_lines.append(f"[green][RESOLVED][/green] [{color}]{f.risk}[/{color}] [{f.code}] {f.message}")
    for f in result.new_security_findings:
        color = RISK_COLORS.get(f.risk, "white")
        sec_lines.append(f"[red][NEW][/red]      [{color}]{f.risk}[/{color}] [{f.code}] {f.message}")
    if sec_lines:
        console.print(Panel("\n".join(sec_lines), title="Security Changes", border_style="red"))
    elif not result.a_scan.findings and not result.b_scan.findings:
        console.print(Panel("[green]No security findings in either version.[/green]", title="Security Changes", border_style="green"))

    # ── Full unified diff (optional) ─────────────────────────────────────────
    if unified and result.unified_diff:
        diff_lines = []
        for line in result.unified_diff:
            if line.startswith("+") and not line.startswith("+++"):
                diff_lines.append(f"[green]{line}[/green]")
            elif line.startswith("-") and not line.startswith("---"):
                diff_lines.append(f"[red]{line}[/red]")
            elif line.startswith("@@"):
                diff_lines.append(f"[cyan]{line}[/cyan]")
            else:
                diff_lines.append(f"[dim]{line}[/dim]")
        console.print(Panel("\n".join(diff_lines), title="Unified Diff", border_style="dim"))


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
