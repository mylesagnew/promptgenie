import sys
from pathlib import Path

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.benchmarker import (
    DEFAULT_MODEL,
    MAX_RUNS,
    RUBRIC_DIMENSIONS,
    AnthropicProvider,
    compare_benchmarks,
    run_benchmark,
)
from promptgenie.core.fileio import safe_read_text, safe_write_text
from promptgenie.core.scanner import scan
from promptgenie.renderers.rich import console, score_color


def _presend_check(prompt_file: str, label: str = "") -> bool:
    """Scan prompt for secrets and warn.

    Returns True if potential secrets were detected (caller must gate on this),
    False if no secret findings.  Uses safe_read_text() so the 1 MB bound is
    enforced consistently with every other file-read in the CLI.
    """
    text = safe_read_text(prompt_file)
    result = scan(text)
    # All secret rules share code="SEC_SECRET" — filter by exact code match.
    # (SecurityFinding has no category field; category lives on ScanRule only.)
    secret_findings = [f for f in result.findings if f.code == "SEC_SECRET"]
    tag = f" ({label})" if label else ""

    console.print(
        f"\n[bold yellow]External transmission notice{tag}:[/bold yellow] "
        f"[bold]{prompt_file}[/bold] will be sent to the benchmark model and judge model."
    )

    if secret_findings:
        console.print(
            f"[bold red]Warning:[/bold red] {len(secret_findings)} potential secret(s) detected:"
        )
        for f in secret_findings:
            console.print(f"  [red]•[/red] Line {f.line}: {f.message}")
        console.print(
            "[red]Sending this file externally may expose sensitive credentials.[/red]"
        )
        return True  # secrets found

    return False  # no secrets found


@click.command(name="benchmark")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.option("--model", "-m", default=DEFAULT_MODEL, help="Claude model to benchmark against.")
@click.option(
    "--runs",
    "-n",
    default=1,
    type=click.IntRange(min=1, max=MAX_RUNS),
    help=f"Number of runs (averages scores, max {MAX_RUNS}).",
)
@click.option(
    "--compare",
    "-c",
    default=None,
    type=click.Path(exists=True),
    help="Second prompt file to compare against.",
)
@click.option(
    "--api-key",
    default=None,
    envvar="ANTHROPIC_API_KEY",
    help="Anthropic API key (or set ANTHROPIC_API_KEY).",
)
@click.option(
    "--out", "-o", default=None, type=click.Path(), help="Save the model response to file."
)
@click.option("--force", is_flag=True, help="Overwrite --out file if it already exists.")
@click.option("--show-response", is_flag=True, help="Print the full model response.")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip external-send confirmation (for CI). Blocked if secrets are detected — "
    "use --allow-secrets to override.",
)
@click.option(
    "--allow-secrets",
    is_flag=True,
    default=False,
    help="Allow external send even when potential secrets are detected. Use with caution.",
)
def benchmark_cmd(
    prompt_file, model, runs, compare, api_key, out, force, show_response, yes, allow_secrets
):
    """Run a prompt against a Claude model and score the output with a rubric."""
    # Pre-send privacy check: scan for secrets and confirm external transmission
    files_to_check = [(prompt_file, ""), (compare, "compare")] if compare else [(prompt_file, "")]
    any_secrets = False
    for fpath, label in files_to_check:
        if fpath and _presend_check(fpath, label):
            any_secrets = True

    if any_secrets and not allow_secrets:
        console.print(
            "\n[bold red]Aborted:[/bold red] potential secrets detected. "
            "Review the warnings above.\n"
            "To send anyway, re-run with [bold]--allow-secrets[/bold]."
        )
        sys.exit(1)

    if not yes:
        try:
            confirmed = click.confirm("\nProceed and send to the model API?", default=False)
        except click.Abort:
            confirmed = False
        if not confirmed:
            console.print("[yellow]Aborted.[/yellow]")
            sys.exit(0)
    else:
        console.print("[dim]--yes passed, skipping confirmation.[/dim]")

    console.print()
    total_calls = runs * (
        2 if not compare else 4
    )  # 2 calls per run (model + judge), doubled if comparing
    console.print(
        f"[dim]Benchmark: {total_calls} API call(s) across {runs} run(s) — model=[bold]{model}[/bold][/dim]"
    )
    try:
        provider = AnthropicProvider(api_key=api_key)
    except (ValueError, ImportError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    try:
        with console.status(f"[bold blue]Benchmarking {prompt_file} against {model}…"):
            results_a = run_benchmark(prompt_file, model=model, runs=runs, provider=provider)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    if any(r.judge_parse_failed for r in results_a):
        console.print(
            "[yellow]Warning:[/yellow] judge model returned an unparseable response on one or more runs. Scores for those runs are omitted."
        )

    results_b = None
    if compare:
        with console.status(f"[bold blue]Benchmarking {compare}…"):
            results_b = run_benchmark(compare, model=model, runs=runs, provider=provider)

    console.print()

    def _render_run(run, title: str) -> None:
        score_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        score_table.add_column("Dimension", style="dim")
        score_table.add_column("Score", justify="right")
        for dim in RUBRIC_DIMENSIONS:
            val = run.rubric_scores.get(dim, 0)
            score_table.add_row(dim.replace("_", " ").title(), f"[{score_color(val)}]{val}[/]")
        score_table.add_row("", "")
        score_table.add_row(
            "[bold]Overall[/bold]",
            f"[{score_color(run.overall_score)} bold]{run.overall_score}/100[/]",
        )
        score_table.add_row("[dim]Model[/dim]", f"[dim]{run.model}[/dim]")
        score_table.add_row("[dim]Latency[/dim]", f"[dim]{run.latency_s}s[/dim]")
        score_table.add_row(
            "[dim]Tokens (in/out)[/dim]", f"[dim]{run.input_tokens:,} / {run.output_tokens:,}[/dim]"
        )
        if run.cache_read_tokens or run.cache_write_tokens:
            score_table.add_row(
                "[dim]Cache (read/write)[/dim]",
                f"[dim]{run.cache_read_tokens:,} / {run.cache_write_tokens:,}[/dim]",
            )
        score_table.add_row("[dim]Est. cost[/dim]", f"[dim]${run.estimated_cost_usd:.4f}[/dim]")
        console.print(Panel(score_table, title=title, border_style="blue"))

        if run.reasoning:
            reasons = [r.strip() for r in run.reasoning.split("|")]
            reason_lines = "\n".join(
                f"[dim]{RUBRIC_DIMENSIONS[i].replace('_', ' ').title()}:[/dim] {r}"
                for i, r in enumerate(reasons)
                if r
            )
            if reason_lines:
                console.print(Panel(reason_lines, title="Judge Reasoning", border_style="dim"))

        if show_response:
            console.print(Panel(run.response_text, title="Model Response", border_style="dim"))
        if out:
            try:
                safe_write_text(out, run.response_text, force=force)
                console.print(f"[green]Response saved to {out}[/green]")
            except FileExistsError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)

    if runs == 1:
        _render_run(results_a[0], f"Benchmark  {prompt_file}")
    else:
        avg_score = int(sum(r.overall_score for r in results_a) / runs)
        avg_latency = round(sum(r.latency_s for r in results_a) / runs, 2)
        avg_cost = round(sum(r.estimated_cost_usd for r in results_a) / runs, 6)
        dim_avgs = {
            d: int(sum(r.rubric_scores.get(d, 0) for r in results_a) / runs)
            for d in RUBRIC_DIMENSIONS
        }

        avg_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        avg_table.add_column("Dimension", style="dim")
        avg_table.add_column("Avg Score", justify="right")
        for dim, val in dim_avgs.items():
            avg_table.add_row(dim.replace("_", " ").title(), f"[{score_color(val)}]{val}[/]")
        avg_table.add_row("", "")
        avg_table.add_row(
            "[bold]Overall avg[/bold]", f"[{score_color(avg_score)} bold]{avg_score}/100[/]"
        )
        avg_table.add_row("[dim]Runs[/dim]", f"[dim]{runs}[/dim]")
        avg_table.add_row("[dim]Avg latency[/dim]", f"[dim]{avg_latency}s[/dim]")
        avg_table.add_row("[dim]Avg cost[/dim]", f"[dim]${avg_cost:.4f}[/dim]")
        console.print(
            Panel(avg_table, title=f"Benchmark  {prompt_file}  ({runs} runs)", border_style="blue")
        )

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
            d = b_val - a_val
            color = "green" if d > 0 else ("red" if d < 0 else "dim")
            prefix = "+" if d > 0 else ""
            cmp_table.add_row(
                dim.replace("_", " ").title(),
                f"[{score_color(a_val)}]{a_val}[/]",
                f"[{score_color(b_val)}]{b_val}[/]",
                f"[{color}]{prefix}{d}[/{color}]",
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
