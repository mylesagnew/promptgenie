"""diff.py — compare two prompt versions.

Supported output formats: rich (default), json, yaml, markdown
Side-by-side view: --side-by-side (Rich table with A/B columns)
"""

from __future__ import annotations

import difflib
import sys

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie.core.differ import (
    DiffResult,
    build_side_by_side,
    diff_prompts,
    diff_to_json,
    diff_to_markdown,
    diff_to_yaml,
)
from promptgenie.core.errors import EXIT_USAGE
from promptgenie.renderers.rich import (
    RISK_COLORS,
    SEVERITY_COLORS,
    console,
    delta_str,
    diag_console,
    is_structured_mode,
    score_color,
)


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
        diag_console.print(f"[yellow]Warning:[/yellow] could not load config: {exc}")
        return PromptGenieConfig(), None


@click.command(name="diff")
@click.argument("prompt_a", type=click.Path())
@click.argument("prompt_b", type=click.Path())
@click.option("--target", "-t", default="claude", help="Target profile to use for scoring.")
@click.option("--unified", "-u", is_flag=True, help="Show full unified diff.")
@click.option(
    "--side-by-side",
    "-s",
    "side_by_side",
    is_flag=True,
    help="Show A and B side-by-side in a two-column table.",
)
@click.option(
    "--format",
    "output_format",
    default="rich",
    type=click.Choice(["rich", "json", "yaml", "markdown"]),
    help="Output format (default: rich).",
)
@click.option("--out", "-o", default=None, type=click.Path(), help="Write output to file.")
@click.option("--force", is_flag=True, help="Overwrite --out file if it exists.")
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(),
    help="Path to .promptgenie.yaml config file.",
)
@click.option("--no-config", is_flag=True, help="Ignore .promptgenie.yaml; use default settings.")
def diff_cmd(
    prompt_a,
    prompt_b,
    target,
    unified,
    side_by_side,
    output_format,
    out,
    force,
    config_path,
    no_config,
):
    """Compare two prompt versions — token delta, risk delta, quality delta, section changes."""
    if prompt_a == "-" and prompt_b == "-":
        raise click.UsageError("Only one of PROMPT_A / PROMPT_B may be '-' (stdin).")

    cfg, cfg_file = _resolve_config(config_path, no_config)
    with console.status("[bold blue]Diffing prompts…"):
        result = diff_prompts(prompt_a, prompt_b, target=target, config=cfg)

    # ── Structured output (json / yaml / markdown) ────────────────────────
    if is_structured_mode(output_format) or output_format == "markdown":
        if output_format == "json":
            output = diff_to_json(result)
        elif output_format == "yaml":
            output = diff_to_yaml(result)
        else:  # markdown
            output = diff_to_markdown(result)

        if out:
            _write_output(out, output, force)
        else:
            click.echo(output)
        sys.exit(0)

    # ── Rich terminal output ──────────────────────────────────────────────
    console.print()
    if cfg_file:
        diag_console.print(f"[dim]Config: {cfg_file}[/dim]")
    console.print(f"[bold]Comparing[/bold]  [cyan]{prompt_a}[/cyan]  →  [cyan]{prompt_b}[/cyan]\n")

    _render_summary_table(result)
    _render_score_table(result)
    _render_section_changes(result)
    _render_lint_changes(result)
    _render_security_changes(result)

    if side_by_side:
        _render_side_by_side(result)

    if unified and result.unified_diff:
        _render_unified_diff(result)

    if out:
        _write_output(out, diff_to_json(result), force)


# ---------------------------------------------------------------------------
# Rich rendering helpers
# ---------------------------------------------------------------------------


def _render_summary_table(result: DiffResult) -> None:
    summary = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    summary.add_column("Metric", style="dim")
    summary.add_column("Version A", justify="right")
    summary.add_column("Version B", justify="right")
    summary.add_column("Delta", justify="right")
    summary.add_row(
        "Tokens",
        str(result.a_tokens),
        str(result.b_tokens),
        delta_str(result.token_delta, invert=True),
    )
    summary.add_row(
        "Quality score",
        f"{result.a_score['total']}/100",
        f"{result.b_score['total']}/100",
        delta_str(result.score_delta),
    )
    summary.add_row(
        "Lint issues",
        str(len(result.a_lint.issues)),
        str(len(result.b_lint.issues)),
        delta_str(result.lint_delta, invert=True),
    )
    summary.add_row(
        "Security findings",
        str(len(result.a_scan.findings)),
        str(len(result.b_scan.findings)),
        delta_str(len(result.b_scan.findings) - len(result.a_scan.findings), invert=True),
    )
    console.print(Panel(summary, title="Summary", border_style="blue"))


def _render_score_table(result: DiffResult) -> None:
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


def _render_section_changes(result: DiffResult) -> None:
    STATUS_STYLE = {
        "added": ("green", "ADDED"),
        "removed": ("red", "REMOVED"),
        "changed": ("yellow", "CHANGED"),
        "unchanged": ("dim", "UNCHANGED"),
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


def _render_lint_changes(result: DiffResult) -> None:
    lint_lines = []
    for issue in result.resolved_lint_issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lint_lines.append(
            f"[green][RESOLVED][/green] [{color}]{issue.severity}[/{color}] [{issue.code}] {issue.message}"
        )
    for issue in result.new_lint_issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lint_lines.append(
            f"[red][NEW][/red]      [{color}]{issue.severity}[/{color}] [{issue.code}] {issue.message}"
        )
    if lint_lines:
        console.print(Panel("\n".join(lint_lines), title="Lint Changes", border_style="yellow"))


def _render_security_changes(result: DiffResult) -> None:
    sec_lines = []
    for f in result.resolved_security_findings:
        color = RISK_COLORS.get(f.risk, "white")
        sec_lines.append(
            f"[green][RESOLVED][/green] [{color}]{f.risk}[/{color}] [{f.code}] {f.message}"
        )
    for f in result.new_security_findings:
        color = RISK_COLORS.get(f.risk, "white")
        sec_lines.append(
            f"[red][NEW][/red]      [{color}]{f.risk}[/{color}] [{f.code}] {f.message}"
        )
    if sec_lines:
        console.print(Panel("\n".join(sec_lines), title="Security Changes", border_style="red"))
    elif not result.a_scan.findings and not result.b_scan.findings:
        console.print(
            Panel(
                "[green]No security findings in either version.[/green]",
                title="Security Changes",
                border_style="green",
            )
        )


def _render_side_by_side(result: DiffResult) -> None:
    """Render a Rich two-column table with A/B content side-by-side."""
    rows = build_side_by_side(result)

    tbl = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        padding=(0, 1),
        expand=True,
    )
    tbl.add_column(f"A  [dim]{result.a_path}[/dim]", ratio=1, no_wrap=False)
    tbl.add_column(f"B  [dim]{result.b_path}[/dim]", ratio=1, no_wrap=False)

    STATUS_COLORS = {
        "equal": ("dim", "dim"),
        "insert": ("dim", "green"),
        "delete": ("red", "dim"),
        "replace": ("red", "green"),
    }

    for row in rows:
        if row.status.startswith("header:"):
            section_status = row.status.split(":")[1]
            header_color = {
                "added": "green",
                "removed": "red",
                "changed": "yellow",
                "unchanged": "dim",
            }.get(section_status, "dim")
            tbl.add_row(
                f"[bold {header_color}]{row.a_line}[/bold {header_color}]",
                f"[bold {header_color}]{row.b_line}[/bold {header_color}]",
            )
        else:
            ca, cb = STATUS_COLORS.get(row.status, ("", ""))
            a_cell = f"[{ca}]{row.a_line}[/{ca}]" if ca else row.a_line
            b_cell = f"[{cb}]{row.b_line}[/{cb}]" if cb else row.b_line
            tbl.add_row(a_cell, b_cell)

    console.print(Panel(tbl, title="Side-by-Side", border_style="blue"))


def _render_unified_diff(result: DiffResult) -> None:
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


def _write_output(path: str, content: str, force: bool) -> None:
    from promptgenie.core.fileio import safe_write_text

    try:
        safe_write_text(path, content, force=force)
        diag_console.print(f"[dim]Output saved to {path}[/dim]")
    except FileExistsError as e:
        diag_console.print(f"[red]Error:[/red] {e}")
        sys.exit(EXIT_USAGE)
