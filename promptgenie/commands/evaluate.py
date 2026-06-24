"""evaluate.py — ``promptgenie evaluate`` command.

Runs a prompt against one or more provider/model pairs in parallel and
produces a comparative metrics table.

Examples
--------
  promptgenie evaluate prompt.md --models claude,gpt-4.1
  promptgenie evaluate prompt.md --models claude/claude-opus-4-8,ollama/llama3.1
  promptgenie evaluate prompt.md --models claude,gpt-4.1 --format json
  promptgenie evaluate prompt.md --models claude --save-baseline main
  promptgenie evaluate prompt.md --models claude --compare main --fail-on-regression
  promptgenie evaluate prompt.md --models claude --changed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE, PromptGenieError
from promptgenie.renderers.rich import console, diag_console

# Exit code for regression failures (shares EXIT_FAILURE)
EXIT_REGRESSION = EXIT_FAILURE


@click.command("evaluate")
@click.argument("file", default="-", metavar="FILE|-")
@click.option("--models", "-m", default=None, metavar="MODEL[,MODEL...]",
              help="Comma-separated list of provider or provider/model specs. "
                   "E.g. claude,gpt-4.1,ollama/llama3.1")
@click.option("--model", "extra_models", multiple=True,
              help="Add a model spec (repeatable, combined with --models).")
@click.option("--system", default=None,
              help="System prompt text (prepended before the prompt).")
@click.option("--concurrency", "-j", default=4, type=int, show_default=True,
              help="Max parallel provider calls.")
@click.option("--timeout", default=60, type=int, show_default=True,
              help="Per-model timeout in seconds.")
@click.option("--max-tokens", default=1024, type=int, show_default=True,
              help="Max output tokens per model.")
@click.option("--determinism-runs", default=1, type=int, show_default=True,
              help="Extra runs per model to measure output determinism (1 = skip).")
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json", "sarif"], case_sensitive=False),
              default="rich", show_default=True)
@click.option("--save-baseline", "save_baseline_name", default=None, metavar="NAME",
              help="Save results as a named baseline artifact.")
@click.option("--compare", "compare_baseline_name", default=None, metavar="NAME",
              help="Compare results against a saved baseline.")
@click.option("--fail-on-regression", is_flag=True,
              help="Exit 1 if comparison finds any metric regression.")
@click.option("--score-drop-threshold", default=5.0, type=float, show_default=True,
              help="Rubric score drop (pts) that counts as a regression.")
@click.option("--cost-increase-pct", default=20.0, type=float, show_default=True,
              help="Cost increase %% that counts as a regression.")
@click.option("--latency-increase-pct", default=None, type=float,
              help="Optional latency increase %% threshold for regression.")
@click.option("--no-high-risk-gate", is_flag=True,
              help="Do not fail on new HIGH/CRITICAL scan findings vs baseline.")
@click.option("--changed", is_flag=True,
              help="Only run if this file is in the git-changed set.")
@click.option("--base-ref", default="origin/main", show_default=True,
              help="Git base ref for --changed detection.")
@click.option("--summary", "summary_path", default=None, envvar="GITHUB_STEP_SUMMARY",
              help="Write Markdown step summary to this path (auto-set in GitHub Actions).")
def evaluate_cmd(
    file: str,
    models: str | None,
    extra_models: tuple[str, ...],
    system: str | None,
    concurrency: int,
    timeout: int,
    max_tokens: int,
    determinism_runs: int,
    output_format: str,
    save_baseline_name: str | None,
    compare_baseline_name: str | None,
    fail_on_regression: bool,
    score_drop_threshold: float,
    cost_increase_pct: float,
    latency_increase_pct: float | None,
    no_high_risk_gate: bool,
    changed: bool,
    base_ref: str,
    summary_path: str | None,
) -> None:
    """Run a prompt against multiple models and compare metrics.

    FILE can be a path or '-' to read from stdin.

    \b
    Examples:
      promptgenie evaluate prompt.md --models claude,gpt-4.1,ollama/llama3.1
      promptgenie evaluate prompt.md --models claude --save-baseline main
      promptgenie evaluate prompt.md --models claude --compare main --fail-on-regression
      cat prompt.md | promptgenie evaluate - --models claude --format json
    """
    from promptgenie.core.fileio import safe_read_text

    # ── --changed gate ───────────────────────────────────────────────────────
    if changed and file != "-":
        from promptgenie.core.change_detector import detect_changed_prompts
        changed_set = detect_changed_prompts(base_ref)
        changed_resolved = {p.resolve() for p in changed_set.files}
        if Path(file).resolve() not in changed_resolved:
            diag_console.print(
                f"[dim]Skipping {file!r} — not in changed set (--changed).[/dim]"
            )
            raise SystemExit(EXIT_OK)

    # ── Read prompt ──────────────────────────────────────────────────────────
    try:
        prompt_text = safe_read_text(file)
    except (OSError, ValueError) as exc:
        diag_console.print(f"[red]Error:[/red] Cannot read {file!r}: {exc}")
        raise SystemExit(EXIT_USAGE)

    # ── Resolve model list ───────────────────────────────────────────────────
    model_specs: list[str] = []
    if models:
        model_specs.extend(m.strip() for m in models.split(",") if m.strip())
    model_specs.extend(extra_models)
    if not model_specs:
        diag_console.print(
            "[red]Error:[/red] No models specified. "
            "Use --models claude,gpt-4.1 or --model <spec>."
        )
        raise SystemExit(EXIT_USAGE)

    # ── Run matrix evaluation ────────────────────────────────────────────────
    from promptgenie.core.evaluator import matrix_evaluate

    if output_format == "rich":
        with console.status(
            f"[bold blue]Evaluating across {len(model_specs)} model(s)…[/bold blue]"
        ):
            matrix_result = matrix_evaluate(
                prompt_text,
                model_specs,
                system=system,
                timeout=timeout,
                max_tokens=max_tokens,
                concurrency=concurrency,
                determinism_runs=determinism_runs,
            )
    else:
        matrix_result = matrix_evaluate(
            prompt_text,
            model_specs,
            system=system,
            timeout=timeout,
            max_tokens=max_tokens,
            concurrency=concurrency,
            determinism_runs=determinism_runs,
        )

    # ── Baseline save ────────────────────────────────────────────────────────
    if save_baseline_name:
        from promptgenie.core.baseline import save_baseline
        # Quick scan of the prompt to record scan risk in baseline
        from promptgenie.core.scanner import scan
        scan_result = scan(prompt_text)
        base_path = save_baseline(
            save_baseline_name, matrix_result, scan_risk=scan_result.risk_level
        )
        diag_console.print(
            f"[green]✓[/green] Baseline [bold]{save_baseline_name!r}[/bold] saved to {base_path}"
        )

    # ── Baseline comparison ──────────────────────────────────────────────────
    regression_report = None
    if compare_baseline_name:
        from promptgenie.core.baseline import (
            BaselineThresholds,
            compare_to_baseline,
            load_baseline,
        )
        from promptgenie.core.scanner import scan

        baseline = load_baseline(compare_baseline_name)
        if baseline is None:
            diag_console.print(
                f"[yellow]Warning:[/yellow] No baseline named {compare_baseline_name!r} found. "
                "Skipping regression check."
            )
        else:
            current_risk = scan(prompt_text).risk_level
            thresholds = BaselineThresholds(
                fail_if_score_drops_by=score_drop_threshold,
                fail_if_cost_increases_by_pct=cost_increase_pct,
                fail_if_latency_increases_by_pct=latency_increase_pct,
                fail_if_new_high_risk=not no_high_risk_gate,
            )
            regression_report = compare_to_baseline(
                matrix_result, baseline,
                thresholds, current_scan_risk=current_risk
            )

    # ── Output ───────────────────────────────────────────────────────────────
    if output_format == "json":
        _output_json(matrix_result, regression_report)
    elif output_format == "sarif":
        _output_sarif(matrix_result, regression_report, file)
    else:
        _output_rich(matrix_result, regression_report)

    # ── GitHub Actions reporter ──────────────────────────────────────────────
    from promptgenie.core.gh_reporter import GHReporter, format_matrix_summary
    reporter = GHReporter(summary_path=summary_path)
    if reporter.active or summary_path:
        md = format_matrix_summary(matrix_result, regression_report=regression_report, prompt_file=file)
        reporter.write_step_summary(md)
        if regression_report and regression_report.has_regressions:
            for reg in regression_report.regressions:
                reporter.annotate_regression(reg, file_path=file)

    # ── Exit code ────────────────────────────────────────────────────────────
    if fail_on_regression and regression_report and regression_report.has_regressions:
        raise SystemExit(EXIT_REGRESSION)
    raise SystemExit(EXIT_OK)


# ---------------------------------------------------------------------------
# Output renderers
# ---------------------------------------------------------------------------

def _output_rich(matrix_result: object, regression_report: object | None) -> None:
    from rich.table import Table

    results = matrix_result.results  # type: ignore[attr-defined]
    table = Table(title="Evaluation Matrix", show_header=True, header_style="bold")
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Status", width=7)
    table.add_column("Latency", justify="right", width=9)
    table.add_column("Tokens", justify="right", width=7)
    table.add_column("Cost (USD)", justify="right", width=10)
    table.add_column("Rubric", justify="right", width=7)
    table.add_column("Safety", justify="right", width=7)
    table.add_column("Determ.", justify="right", width=8)

    for r in results:
        m = r.metrics
        if r.ok:
            status = "[green]OK[/green]"
            latency = f"{m.latency_ms:.0f}ms"
            tokens = str(m.total_tokens)
            cost = f"${m.cost_usd:.4f}"
            rubric = f"{m.rubric_score:.0f}" if m.rubric_score is not None else "—"
            safety = f"{m.safety_score:.0f}" if m.safety_score is not None else "—"
            det = f"{m.determinism:.2f}" if m.determinism is not None else "—"
        else:
            status = "[red]ERR[/red]"
            latency = tokens = cost = rubric = safety = det = "—"

        table.add_row(r.display_name, status, latency, tokens, cost, rubric, safety, det)

    console.print()
    console.print(table)

    if regression_report:
        _print_regression_report(regression_report)


def _print_regression_report(report: object) -> None:
    regs = report.regressions  # type: ignore[attr-defined]
    imps = report.improvements  # type: ignore[attr-defined]
    warns = report.warnings  # type: ignore[attr-defined]

    if regs:
        console.print(f"\n[red bold]⚠ {len(regs)} regression(s) vs baseline {report.baseline_name!r}:[/red bold]")  # type: ignore[attr-defined]
        for r in regs:
            console.print(f"  [red]✗[/red] {r.model} [{r.metric}] {r.message}")
    if imps:
        console.print(f"\n[green]{len(imps)} improvement(s):[/green]")
        for i in imps:
            console.print(f"  [green]✓[/green] {i}")
    if warns:
        for w in warns:
            console.print(f"  [yellow]⚠[/yellow] {w}")


def _output_json(matrix_result: object, regression_report: object | None) -> None:
    results = matrix_result.results  # type: ignore[attr-defined]
    data: dict = {
        "schema_version": "1.0",
        "results": [
            {
                "model": r.display_name,
                "provider": r.provider,
                "ok": r.ok,
                "error": r.error,
                "response": r.response,
                "metrics": {
                    "latency_ms": r.metrics.latency_ms,
                    "input_tokens": r.metrics.input_tokens,
                    "output_tokens": r.metrics.output_tokens,
                    "total_tokens": r.metrics.total_tokens,
                    "cost_usd": r.metrics.cost_usd,
                    "rubric_score": r.metrics.rubric_score,
                    "safety_score": r.metrics.safety_score,
                    "determinism": r.metrics.determinism,
                },
            }
            for r in results
        ],
    }
    if regression_report:
        data["regression"] = regression_report.to_dict()  # type: ignore[attr-defined]
    sys.stdout.write(json.dumps(data, indent=2) + "\n")


def _output_sarif(
    matrix_result: object, regression_report: object | None, file_path: str
) -> None:
    results = matrix_result.results  # type: ignore[attr-defined]
    sarif_results = []
    rules = []
    if regression_report and regression_report.has_regressions:  # type: ignore[attr-defined]
        for reg in regression_report.regressions:  # type: ignore[attr-defined]
            rule_id = f"REGRESSION_{reg.metric.upper()}"
            rules.append({
                "id": rule_id,
                "shortDescription": {"text": f"Metric regression: {reg.metric}"},
            })
            loc: dict = {}
            if file_path and file_path != "-":
                loc = {"physicalLocation": {"artifactLocation": {"uri": file_path}}}
            sarif_results.append({
                "ruleId": rule_id,
                "level": "error",
                "message": {"text": reg.message},
                "locations": [loc] if loc else [],
            })

    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "PromptGenie Evaluate",
                    "version": "1.0",
                    "rules": rules,
                }
            },
            "results": sarif_results,
            "properties": {
                "model_count": len(results),
                "ok_count": sum(1 for r in results if r.ok),
                "has_regressions": (
                    regression_report.has_regressions if regression_report else False  # type: ignore[union-attr]
                ),
            },
        }],
    }
    sys.stdout.write(json.dumps(doc, indent=2) + "\n")
