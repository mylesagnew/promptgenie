import difflib

import click
from rich.panel import Panel
from rich.table import Table
from rich import box

from promptgenie.core.differ import diff_prompts
from promptgenie.renderers.rich import (
    console, score_color, SEVERITY_COLORS, RISK_COLORS, delta_str,
)


@click.command(name="diff")
@click.argument("prompt_a", type=click.Path(exists=True))
@click.argument("prompt_b", type=click.Path(exists=True))
@click.option("--target", "-t", default="claude", help="Target profile to use for scoring.")
@click.option("--unified", "-u", is_flag=True, help="Show full unified diff.")
def diff_cmd(prompt_a, prompt_b, target, unified):
    """Compare two prompt versions — token delta, risk delta, quality delta, section changes."""
    with console.status("[bold blue]Diffing prompts…"):
        result = diff_prompts(prompt_a, prompt_b, target=target)

    console.print()
    console.print(f"[bold]Comparing[/bold]  [cyan]{prompt_a}[/cyan]  →  [cyan]{prompt_b}[/cyan]\n")

    summary = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    summary.add_column("Metric", style="dim")
    summary.add_column("Version A", justify="right")
    summary.add_column("Version B", justify="right")
    summary.add_column("Delta", justify="right")
    summary.add_row("Tokens", str(result.a_tokens), str(result.b_tokens),
                    delta_str(result.token_delta, invert=True))
    summary.add_row("Quality score", f"{result.a_score['total']}/100", f"{result.b_score['total']}/100",
                    delta_str(result.score_delta))
    summary.add_row("Lint issues", str(len(result.a_lint.issues)), str(len(result.b_lint.issues)),
                    delta_str(result.lint_delta, invert=True))
    summary.add_row("Security findings", str(len(result.a_scan.findings)), str(len(result.b_scan.findings)),
                    delta_str(len(result.b_scan.findings) - len(result.a_scan.findings), invert=True))
    console.print(Panel(summary, title="Summary", border_style="blue"))

    score_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    score_table.add_column("Dimension", style="dim")
    score_table.add_column("A", justify="right")
    score_table.add_column("B", justify="right")
    score_table.add_column("Δ", justify="right")
    for dim, a_val in result.a_score["breakdown"].items():
        b_val = result.b_score["breakdown"].get(dim, 0)
        score_table.add_row(
            dim.replace("_", " ").title(),
            f"[{score_color(a_val)}]{a_val}[/]",
            f"[{score_color(b_val)}]{b_val}[/]",
            delta_str(b_val - a_val),
        )
    console.print(Panel(score_table, title="Quality Score Breakdown", border_style="dim"))

    STATUS_STYLE = {
        "added":     ("green",  "ADDED"),
        "removed":   ("red",    "REMOVED"),
        "changed":   ("yellow", "CHANGED"),
        "unchanged": ("dim",    "UNCHANGED"),
    }
    section_lines = []
    for d in result.section_deltas:
        if d.name == "__preamble__":
            continue
        color, label = STATUS_STYLE[d.status]
        section_lines.append(f"[{color}][{label}][/{color}]  {d.name}")
        if d.status == "changed":
            inline = list(difflib.unified_diff(d.a_lines, d.b_lines, lineterm="", n=1))
            for line in inline[2:]:
                if line.startswith("+"):
                    section_lines.append(f"  [green]{line}[/green]")
                elif line.startswith("-"):
                    section_lines.append(f"  [red]{line}[/red]")
    if section_lines:
        console.print(Panel("\n".join(section_lines), title="Section Changes", border_style="dim"))

    lint_lines = []
    for issue in result.resolved_lint_issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lint_lines.append(f"[green][RESOLVED][/green] [{color}]{issue.severity}[/{color}] [{issue.code}] {issue.message}")
    for issue in result.new_lint_issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lint_lines.append(f"[red][NEW][/red]      [{color}]{issue.severity}[/{color}] [{issue.code}] {issue.message}")
    if lint_lines:
        console.print(Panel("\n".join(lint_lines), title="Lint Changes", border_style="yellow"))

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
        console.print(Panel("[green]No security findings in either version.[/green]",
                            title="Security Changes", border_style="green"))

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
