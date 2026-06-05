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
from promptgenie.core.tester import run_test_suite
from promptgenie.core.benchmarker import run_benchmark, compare_benchmarks, DEFAULT_MODEL, RUBRIC_DIMENSIONS
from promptgenie.core.context_packs import list_packs, load_pack, render_pack, inject_pack_into_prompt, init_pack, SECTION_MAP
from promptgenie.core.workflow import generate_workflow, save_workflow
from promptgenie.core.ci import init_ci, ci_status

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
@click.option("--pack", "-p", default=None, help="Context pack ID to inject (e.g. react-supabase-app).")
@click.option("--no-lint", is_flag=True, help="Skip automatic lint pass.")
@click.option("--no-scan", is_flag=True, help="Skip automatic security scan.")
def generate(task, target, template, context, output_format, constraints, mode, out, pack, no_lint, no_scan):
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


@cli.command(name="test")
@click.argument("test_file", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show all assertions, not just failures.")
def test_cmd(test_file, verbose):
    """Run a prompt test suite (.prompt-test.yaml)."""
    try:
        with console.status("[bold blue]Running tests…"):
            result = run_test_suite(test_file)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print()

    # ── Header ───────────────────────────────────────────────────────────────
    status_color = "green" if result.passed else "red"
    status_label = "PASSED" if result.passed else "FAILED"
    console.print(Panel(
        f"[bold {status_color}]{status_label}[/bold {status_color}]  "
        f"{result.pass_count}/{result.total} tests passed"
        + (f"\n[dim]{result.description}[/dim]" if result.description else ""),
        title=f"Test Suite  [dim]{test_file}[/dim]",
        border_style=status_color,
    ))

    # ── Per-test results ─────────────────────────────────────────────────────
    for case in result.cases:
        icon = "[green]✓[/green]" if case.passed else "[red]✗[/red]"
        console.print(f"\n  {icon}  [bold]{case.name}[/bold]")

        for assertion in case.assertions:
            if not assertion.passed:
                console.print(f"      [red]FAIL[/red]  {assertion.detail}")
                console.print(f"             [dim]actual: {assertion.actual}[/dim]")
            elif verbose:
                console.print(f"      [green]PASS[/green]  [dim]{assertion.detail}[/dim]")

    console.print()
    sys.exit(0 if result.passed else 1)


@cli.command(name="benchmark")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.option("--model", "-m", default=DEFAULT_MODEL, help="Claude model to benchmark against.")
@click.option("--runs", "-n", default=1, type=int, help="Number of runs (averages scores).")
@click.option("--compare", "-c", default=None, type=click.Path(exists=True),
              help="Second prompt file to compare against.")
@click.option("--api-key", default=None, envvar="ANTHROPIC_API_KEY",
              help="Anthropic API key (or set ANTHROPIC_API_KEY).")
@click.option("--out", "-o", default=None, type=click.Path(),
              help="Save the model response to file.")
@click.option("--show-response", is_flag=True, help="Print the full model response.")
def benchmark_cmd(prompt_file, model, runs, compare, api_key, out, show_response):
    """Run a prompt against a Claude model and score the output with a rubric."""
    try:
        with console.status(f"[bold blue]Benchmarking {prompt_file} against {model}…"):
            results_a = run_benchmark(prompt_file, model=model, api_key=api_key, runs=runs)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    results_b = None
    if compare:
        with console.status(f"[bold blue]Benchmarking {compare}…"):
            results_b = run_benchmark(compare, model=model, api_key=api_key, runs=runs)

    console.print()

    def _render_run(run, title: str):
        # Score breakdown
        score_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        score_table.add_column("Dimension", style="dim")
        score_table.add_column("Score", justify="right")
        for dim in RUBRIC_DIMENSIONS:
            val = run.rubric_scores.get(dim, 0)
            score_table.add_row(dim.replace("_", " ").title(), f"[{score_color(val)}]{val}[/]")
        score_table.add_row("", "")
        score_table.add_row("[bold]Overall[/bold]", f"[{score_color(run.overall_score)} bold]{run.overall_score}/100[/]")
        score_table.add_row("[dim]Model[/dim]", f"[dim]{run.model}[/dim]")
        score_table.add_row("[dim]Latency[/dim]", f"[dim]{run.latency_s}s[/dim]")
        score_table.add_row("[dim]Tokens (in/out)[/dim]", f"[dim]{run.input_tokens:,} / {run.output_tokens:,}[/dim]")
        if run.cache_read_tokens or run.cache_write_tokens:
            score_table.add_row("[dim]Cache (read/write)[/dim]",
                                f"[dim]{run.cache_read_tokens:,} / {run.cache_write_tokens:,}[/dim]")
        score_table.add_row("[dim]Est. cost[/dim]", f"[dim]${run.estimated_cost_usd:.4f}[/dim]")
        console.print(Panel(score_table, title=title, border_style="blue"))

        # Reasoning
        if run.reasoning:
            reasons = [r.strip() for r in run.reasoning.split("|")]
            reason_lines = "\n".join(
                f"[dim]{RUBRIC_DIMENSIONS[i].replace('_',' ').title()}:[/dim] {r}"
                for i, r in enumerate(reasons) if r
            )
            if reason_lines:
                console.print(Panel(reason_lines, title="Judge Reasoning", border_style="dim"))

        # Response
        if show_response or out:
            if show_response:
                console.print(Panel(run.response_text, title="Model Response", border_style="dim"))
            if out:
                Path(out).write_text(run.response_text)
                console.print(f"[green]Response saved to {out}[/green]")

    if runs == 1:
        _render_run(results_a[0], f"Benchmark  {prompt_file}")
    else:
        # Average across runs
        avg_score = int(sum(r.overall_score for r in results_a) / runs)
        avg_latency = round(sum(r.latency_s for r in results_a) / runs, 2)
        avg_cost = round(sum(r.estimated_cost_usd for r in results_a) / runs, 6)
        dim_avgs = {d: int(sum(r.rubric_scores.get(d, 0) for r in results_a) / runs) for d in RUBRIC_DIMENSIONS}

        avg_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        avg_table.add_column("Dimension", style="dim")
        avg_table.add_column("Avg Score", justify="right")
        for dim, val in dim_avgs.items():
            avg_table.add_row(dim.replace("_", " ").title(), f"[{score_color(val)}]{val}[/]")
        avg_table.add_row("", "")
        avg_table.add_row("[bold]Overall avg[/bold]", f"[{score_color(avg_score)} bold]{avg_score}/100[/]")
        avg_table.add_row("[dim]Runs[/dim]", f"[dim]{runs}[/dim]")
        avg_table.add_row("[dim]Avg latency[/dim]", f"[dim]{avg_latency}s[/dim]")
        avg_table.add_row("[dim]Avg cost[/dim]", f"[dim]${avg_cost:.4f}[/dim]")
        console.print(Panel(avg_table, title=f"Benchmark  {prompt_file}  ({runs} runs)", border_style="blue"))

    # ── Comparison ───────────────────────────────────────────────────────────
    if results_b:
        comparison = compare_benchmarks(results_a, results_b)
        a_avg = comparison["a"]
        b_avg = comparison["b"]

        cmp_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        cmp_table.add_column("Dimension", style="dim")
        cmp_table.add_column(f"A: {Path(prompt_file).name}", justify="right")
        cmp_table.add_column(f"B: {Path(compare).name}", justify="right")
        cmp_table.add_column("Δ", justify="right")

        for dim in RUBRIC_DIMENSIONS:
            a_val = a_avg["scores"][dim]
            b_val = b_avg["scores"][dim]
            delta = b_val - a_val
            color = "green" if delta > 0 else ("red" if delta < 0 else "dim")
            prefix = "+" if delta > 0 else ""
            cmp_table.add_row(
                dim.replace("_", " ").title(),
                f"[{score_color(a_val)}]{a_val}[/]",
                f"[{score_color(b_val)}]{b_val}[/]",
                f"[{color}]{prefix}{delta}[/{color}]",
            )

        cmp_table.add_row("", "", "", "")
        a_ov, b_ov = a_avg["overall"], b_avg["overall"]
        d_ov = b_ov - a_ov
        color = "green" if d_ov > 0 else ("red" if d_ov < 0 else "dim")
        prefix = "+" if d_ov > 0 else ""
        cmp_table.add_row(
            "[bold]Overall[/bold]",
            f"[{score_color(a_ov)} bold]{a_ov}/100[/]",
            f"[{score_color(b_ov)} bold]{b_ov}/100[/]",
            f"[{color} bold]{prefix}{d_ov}[/{color} bold]",
        )
        cmp_table.add_row(
            "[dim]Avg tokens[/dim]",
            f"[dim]{a_avg['avg_tokens']:,}[/dim]",
            f"[dim]{b_avg['avg_tokens']:,}[/dim]",
            "",
        )
        cmp_table.add_row(
            "[dim]Avg cost[/dim]",
            f"[dim]${a_avg['avg_cost']:.4f}[/dim]",
            f"[dim]${b_avg['avg_cost']:.4f}[/dim]",
            "",
        )
        console.print(Panel(cmp_table, title="Prompt Comparison", border_style="cyan"))


@cli.command(name="workflow")
@click.argument("workflow_file", type=click.Path(exists=True))
@click.option("--out", "-o", default=None, type=click.Path(),
              help="Directory to save individual step prompts (one file per step).")
@click.option("--step", "-s", default=None, type=int,
              help="Show only a specific step number.")
@click.option("--summary", is_flag=True, help="Show workflow summary only — no prompt content.")
def workflow_cmd(workflow_file, out, step, summary):
    """Generate a staged prompt chain from a .workflow.yaml file."""
    with console.status("[bold blue]Building workflow…"):
        try:
            result = generate_workflow(workflow_file)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

    console.print()

    # ── Summary panel ────────────────────────────────────────────────────────
    summary_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary_table.add_column("", style="dim")
    summary_table.add_column("")
    summary_table.add_row("Workflow", f"[bold]{result.name}[/bold]")
    if result.description:
        summary_table.add_row("Description", result.description)
    summary_table.add_row("Target", result.target)
    summary_table.add_row("Steps", str(len(result.steps)))
    summary_table.add_row("Total tokens", f"{result.total_tokens:,}")
    gates = result.approval_gates
    if gates:
        gate_names = ", ".join(f"Step {g.step_number} ({g.step.name})" for g in gates)
        summary_table.add_row("[yellow]Approval gates[/yellow]", gate_names)

    console.print(Panel(summary_table, title=f"Workflow — {workflow_file}", border_style="blue"))

    # Step index
    step_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    step_table.add_column("#", style="dim", justify="right")
    step_table.add_column("Step")
    step_table.add_column("Depends on", style="dim")
    step_table.add_column("Tokens", justify="right", style="dim")
    step_table.add_column("Gate", justify="center")
    for rs in result.steps:
        gate = "[yellow]✓[/yellow]" if rs.step.requires_approval else ""
        dep = rs.step.depends_on or "—"
        step_table.add_row(str(rs.step_number), rs.step.name, dep, str(rs.token_estimate), gate)
    console.print(Panel(step_table, title="Step Index", border_style="dim"))

    if summary:
        return

    # ── Individual step prompts ──────────────────────────────────────────────
    steps_to_show = result.steps
    if step is not None:
        steps_to_show = [rs for rs in result.steps if rs.step_number == step]
        if not steps_to_show:
            console.print(f"[red]Step {step} not found.[/red]")
            sys.exit(1)

    for rs in steps_to_show:
        gate_label = "  [yellow][APPROVAL GATE][/yellow]" if rs.step.requires_approval else ""
        console.print(Panel(
            rs.prompt_text,
            title=f"Step {rs.step_number}/{rs.total_steps} — {rs.step.name}{gate_label}  [dim]{rs.token_estimate} tokens[/dim]",
            border_style="blue",
        ))

    # ── Save ─────────────────────────────────────────────────────────────────
    if out:
        saved = save_workflow(result, out)
        console.print(f"\n[green]Saved {len(saved)} step prompt(s) to {out}/[/green]")
        for p in saved:
            console.print(f"  [dim]{p.name}[/dim]")


@cli.group(name="ci")
def ci_group():
    """Set up and check CI integrations for prompt quality gates."""


@ci_group.command(name="init")
@click.option("--dir", "target_dir", default=".", type=click.Path(),
              help="Target project directory (default: current directory).")
def ci_init(target_dir):
    """Scaffold GitHub Actions workflow and pre-commit hooks for prompt checks."""
    result = init_ci(target_dir)
    created = result["created"]
    skipped = result["skipped"]

    console.print()
    if created:
        for key, path in created.items():
            label = {
                "github_actions": "GitHub Actions workflow",
                "pre_commit":     "pre-commit config",
                "promptignore":   ".promptignore",
            }.get(key, key)
            console.print(f"  [green]Created[/green]  {label}: [dim]{path}[/dim]")

    if skipped:
        for key, path in skipped.items():
            label = {
                "github_actions": "GitHub Actions workflow",
                "pre_commit":     "pre-commit config",
                "promptignore":   ".promptignore",
            }.get(key, key)
            console.print(f"  [yellow]Skipped[/yellow] {label}: already exists at [dim]{path}[/dim]")

    console.print()
    console.print(Panel(
        "\n".join([
            "[bold]GitHub Actions[/bold]",
            "Push or PR touching [dim].md[/dim] / [dim].prompt-test.yaml[/dim] / [dim].workflow.yaml[/dim] files",
            "will automatically run lint, scan, and test jobs.",
            "",
            "[bold]Pre-commit hooks[/bold]",
            "Install with: [cyan]pip install pre-commit && pre-commit install[/cyan]",
            "Hooks run on staged [dim].prompt.md[/dim] and [dim].prompt-test.yaml[/dim] files.",
            "",
            "[bold].promptignore[/bold]",
            "Add paths to exclude from lint/scan checks (supports glob patterns).",
        ]),
        title="CI Integration Ready",
        border_style="green",
    ))


@ci_group.command(name="status")
@click.option("--dir", "target_dir", default=".", type=click.Path(),
              help="Target project directory (default: current directory).")
def ci_status_cmd(target_dir):
    """Check which CI integrations are active in a project directory."""
    status = ci_status(target_dir)

    table = Table(title=f"CI Status — {Path(target_dir).resolve()}", box=box.ROUNDED)
    table.add_column("Integration")
    table.add_column("Status", justify="center")

    labels = {
        "github_actions": "GitHub Actions (prompt-check.yml)",
        "pre_commit":     "Pre-commit hooks (.pre-commit-config.yaml)",
        "promptignore":   ".promptignore exclusion file",
        "is_git_repo":    "Git repository",
    }

    for key, active in status.items():
        icon = "[green]✓ Active[/green]" if active else "[dim]✗ Not found[/dim]"
        table.add_row(labels.get(key, key), icon)

    console.print(table)

    if not status.get("is_git_repo"):
        console.print("\n[yellow]Warning:[/yellow] No .git directory found — not a git repository.")

    if not all(status.values()):
        console.print("\n[dim]Run [bold]promptgenie ci init[/bold] to set up missing integrations.[/dim]")


@cli.group(name="pack")
def pack_group():
    """Manage context packs — reusable project context blocks."""


@pack_group.command(name="list")
def pack_list():
    """List all available context packs."""
    packs = list_packs()
    if not packs:
        console.print("[dim]No context packs found. Run [bold]promptgenie pack init <id>[/bold] to create one.[/dim]")
        return
    table = Table(title="Context Packs", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Description", style="dim")
    table.add_column("Stack", style="dim")
    for p in packs:
        stack = ", ".join(p["stack"][:3])
        if len(p["stack"]) > 3:
            stack += f" +{len(p['stack']) - 3} more"
        table.add_row(p["id"], p["name"], p["description"], stack)
    console.print(table)


@pack_group.command(name="show")
@click.argument("pack_id")
@click.option("--mode", "-m", default="standard",
              type=click.Choice(["minimal", "standard", "exhaustive"]),
              help="How much of the pack to render.")
def pack_show(pack_id, mode):
    """Show the rendered context block for a pack."""
    try:
        rendered = render_pack(pack_id, mode=mode)
        pack = load_pack(pack_id)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    console.print(Panel(rendered, title=f"Context Pack — {pack.get('name', pack_id)}  [dim]mode: {mode}[/dim]", border_style="cyan"))


@pack_group.command(name="inject")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.argument("pack_id")
@click.option("--mode", "-m", default="standard",
              type=click.Choice(["minimal", "standard", "exhaustive"]))
@click.option("--out", "-o", default=None, type=click.Path(),
              help="Save result to file (defaults to overwrite prompt_file).")
def pack_inject(prompt_file, pack_id, mode, out):
    """Inject a context pack into an existing prompt file."""
    try:
        prompt_text = Path(prompt_file).read_text()
        result = inject_pack_into_prompt(prompt_text, pack_id, mode=mode)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    dest = out or prompt_file
    Path(dest).write_text(result)
    console.print(Panel(result, title=f"Injected — {pack_id} → {dest}", border_style="cyan"))
    console.print(f"[green]Saved to {dest}[/green]")


@pack_group.command(name="init")
@click.argument("pack_id")
@click.option("--name", default="", help="Human-readable name for the pack.")
@click.option("--description", default="", help="One-line description.")
def pack_init(pack_id, name, description):
    """Create a new blank context pack file."""
    try:
        path = init_pack(pack_id, name=name, description=description)
        console.print(f"[green]Created context pack:[/green] {path}")
        console.print(f"[dim]Edit the file to fill in your project details, then use:[/dim]")
        console.print(f"  promptgenie generate \"your task\" --pack {pack_id}")
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


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
