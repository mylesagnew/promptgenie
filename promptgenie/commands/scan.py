"""scan.py — multi-file / directory / zip scanner with optional LLM semantic analysis.

Extends the original single-file scan command with SkillSpector-inspired capabilities:

New flags
---------
--llm               Enable opt-in LLM semantic analysis (off by default)
--no-external-llm   Privacy/air-gap mode — suppress any LLM call even if --llm passed
--max-files N       Cap the number of files scanned (default 500)
--max-bytes N       Cap total bytes across all files (default 10 MB)
--max-file-bytes N  Skip individual files over this size (default 1 MB)
--fail-on-severity  CI gate: exit 1 when any finding meets or exceeds this level
--show-skipped      Print the list of excluded files after scanning

Single-file mode (original behaviour) is preserved when a single file path is
given that is not a directory or zip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie.core.fileio import FileTooLargeError, safe_read_text, safe_write_text
from promptgenie.core.formatters import (
    multi_scan_to_json,
    multi_scan_to_sarif,
    scan_to_json,
    scan_to_sarif,
)
from promptgenie.core.input_handler import (
    CollectResult,
    collect_files,
)
from promptgenie.core.llm_analyzer import LLMAnalysisConfig, LLMAnalysisResult, analyze_with_llm
from promptgenie.core.scanner import ScanResult, scan
from promptgenie.renderers.rich import console, format_scan_findings

# ---------------------------------------------------------------------------
# Severity ordering (for --fail-on-severity gate)
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _severity_at_or_above(finding_risk: str, threshold: str) -> bool:
    return _SEVERITY_ORDER.get(finding_risk, 0) >= _SEVERITY_ORDER.get(threshold, 0)


def _any_finding_at_or_above(scan_results: list[ScanResult], threshold: str) -> bool:
    for r in scan_results:
        for f in r.findings:
            if _severity_at_or_above(f.risk, threshold):
                return True
    return False


# ---------------------------------------------------------------------------
# Config loader (shared with other commands)
# ---------------------------------------------------------------------------


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
        raise


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command(name="scan")
@click.argument("paths", nargs=-1, required=True, type=click.Path())
@click.option(
    "--format",
    "output_format",
    default="rich",
    type=click.Choice(["rich", "json", "sarif"]),
    help="Output format (default: rich).",
)
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(),
    help="Write output to file instead of stdout.",
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
    help="Fall back to default settings when the config file cannot be loaded.",
)
# ── SkillSpector-inspired flags ─────────────────────────────────────────────
@click.option(
    "--llm",
    "enable_llm",
    is_flag=True,
    default=False,
    help=(
        "Enable opt-in LLM semantic analysis. OFF by default. "
        "Requires the OPENAI_API_KEY environment variable (or equivalent). "
        "Content is redacted of known secrets before being sent."
    ),
)
@click.option(
    "--no-external-llm",
    "no_external_llm",
    is_flag=True,
    default=False,
    help=(
        "Privacy / air-gap mode — suppress any external LLM call even if --llm was passed. "
        "Static heuristic scanning still runs."
    ),
)
@click.option(
    "--max-files",
    default=500,
    type=click.IntRange(min=1),
    show_default=True,
    help="Maximum number of files scanned in directory/zip mode.",
)
@click.option(
    "--max-bytes",
    default=10 * 1024 * 1024,
    type=click.IntRange(min=1),
    show_default=True,
    help="Maximum total bytes across all collected files (default 10 MB).",
)
@click.option(
    "--max-file-bytes",
    default=1 * 1024 * 1024,
    type=click.IntRange(min=1),
    show_default=True,
    help="Skip individual files larger than this many bytes (default 1 MB).",
)
@click.option(
    "--fail-on-severity",
    "fail_on_severity",
    default=None,
    type=click.Choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"], case_sensitive=False),
    help=(
        "Exit 1 when any finding meets or exceeds this severity level. "
        "Without this flag, exit 1 only on HIGH/CRITICAL (original behaviour)."
    ),
)
@click.option(
    "--show-skipped",
    is_flag=True,
    default=False,
    help="Print a table of files that were excluded (size, wrong type, etc.).",
)
def scan_cmd(
    paths,
    output_format,
    out,
    force,
    config_path,
    no_config,
    best_effort,
    enable_llm,
    no_external_llm,
    max_files,
    max_bytes,
    max_file_bytes,
    fail_on_severity,
    show_skipped,
):
    """Scan prompt file(s), directory, or zip archive for security risks.

    PATHS may be one or more files, a directory, or a .zip archive.
    Single-file mode preserves the original behaviour.
    """
    # ── Config ───────────────────────────────────────────────────────────────
    try:
        cfg, cfg_file = _resolve_config(config_path, no_config, best_effort=best_effort)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        console.print(
            "[dim]Use --best-effort to fall back to defaults, or --no-config to skip.[/dim]"
        )
        sys.exit(1)

    # ── LLM config ───────────────────────────────────────────────────────────
    llm_config = LLMAnalysisConfig(
        enabled=enable_llm,
        privacy_mode=no_external_llm,
    )

    # ── Determine single-file vs multi-file mode ──────────────────────────────
    path_list = list(paths)
    is_single_file = len(path_list) == 1 and (
        path_list[0] == "-"
        or (Path(path_list[0]).is_file() and Path(path_list[0]).suffix.lower() != ".zip")
    )

    if is_single_file:
        _run_single_file(
            path_list[0],
            output_format,
            out,
            force,
            cfg,
            cfg_file,
            llm_config,
            fail_on_severity,
        )
    else:
        _run_multi(
            path_list,
            output_format,
            out,
            force,
            cfg,
            cfg_file,
            llm_config,
            max_files,
            max_bytes,
            max_file_bytes,
            fail_on_severity,
            show_skipped,
        )


# ---------------------------------------------------------------------------
# Single-file path (preserves original behaviour)
# ---------------------------------------------------------------------------


def _run_single_file(
    prompt_file: str,
    output_format: str,
    out: str | None,
    force: bool,
    cfg: PromptGenieConfig,
    cfg_file: str | None,
    llm_config: LLMAnalysisConfig,
    fail_on_severity: str | None,
) -> None:
    display_name = "<stdin>" if prompt_file == "-" else prompt_file
    try:
        text = safe_read_text(prompt_file)
    except FileTooLargeError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    result = scan(text, config=cfg.scanner)
    llm_result: LLMAnalysisResult | None = None

    if llm_config.enabled and not llm_config.privacy_mode:
        with console.status("[bold blue]Running LLM semantic analysis…"):
            llm_result = analyze_with_llm(text, file_path=display_name, config=llm_config)

    if output_format == "json":
        output = scan_to_json(result, prompt_path=display_name)
        _output_or_write(output, out, force)
    elif output_format == "sarif":
        output = scan_to_sarif(result, prompt_path=display_name)
        _output_or_write(output, out, force)
    else:
        _render_single_rich(result, llm_result, display_name, cfg_file)
        if out:
            _write_output(out, scan_to_json(result, prompt_path=display_name), force)

    _exit_for_severity(
        [result],
        fail_on_severity,
        default_high_exit=True,
    )


# ---------------------------------------------------------------------------
# Multi-file / directory / zip path
# ---------------------------------------------------------------------------


def _run_multi(
    path_list: list[str],
    output_format: str,
    out: str | None,
    force: bool,
    cfg: PromptGenieConfig,
    cfg_file: str | None,
    llm_config: LLMAnalysisConfig,
    max_files: int,
    max_bytes: int,
    max_file_bytes: int,
    fail_on_severity: str | None,
    show_skipped: bool,
) -> None:
    # ── Collect files ─────────────────────────────────────────────────────────
    with console.status("[bold blue]Collecting files…"):
        collected: CollectResult = collect_files(
            path_list,
            max_files=max_files,
            max_bytes=max_bytes,
            max_file_bytes=max_file_bytes,
        )

    if collected.file_count == 0:
        console.print("[yellow]No scannable files found.[/yellow]")
        if show_skipped and collected.skipped:
            _render_skipped_table(collected)
        sys.exit(0)

    # ── Scan each file ────────────────────────────────────────────────────────
    scan_results: list[tuple[str, ScanResult, LLMAnalysisResult | None]] = []

    with console.status(f"[bold blue]Scanning {collected.file_count} files…"):
        for cf in collected.files:
            sr = scan(cf.content, config=cfg.scanner)
            lr: LLMAnalysisResult | None = None
            if llm_config.enabled and not llm_config.privacy_mode:
                lr = analyze_with_llm(cf.content, file_path=cf.path, config=llm_config)
            scan_results.append((cf.path, sr, lr))

    scan_result_objs = [sr for _, sr, _ in scan_results]

    # ── Output ────────────────────────────────────────────────────────────────
    if output_format == "json":
        output = multi_scan_to_json(
            [(p, sr) for p, sr, _ in scan_results],
            llm_results=[lr for _, _, lr in scan_results if lr is not None],
        )
        _output_or_write(output, out, force)
    elif output_format == "sarif":
        output = multi_scan_to_sarif([(p, sr) for p, sr, _ in scan_results])
        _output_or_write(output, out, force)
    else:
        if cfg_file:
            console.print(f"[dim]Config: {cfg_file}[/dim]")
        _render_multi_rich(scan_results, collected)
        if show_skipped and collected.skipped:
            _render_skipped_table(collected)
        if out:
            output = multi_scan_to_json(
                [(p, sr) for p, sr, _ in scan_results],
                llm_results=[lr for _, _, lr in scan_results if lr is not None],
            )
            _write_output(out, output, force)

    _exit_for_severity(scan_result_objs, fail_on_severity, default_high_exit=True)


# ---------------------------------------------------------------------------
# Rich rendering helpers
# ---------------------------------------------------------------------------


def _render_single_rich(
    result: ScanResult,
    llm_result: LLMAnalysisResult | None,
    prompt_file: str,
    cfg_file: str | None,
) -> None:
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
                title=(
                    f"Prompt Security Scan (heuristic)  "
                    f"[bold]Risk: {result.risk_level}[/bold]  "
                    f"[dim]{prompt_file}[/dim]"
                ),
                border_style="red",
            )
        )

    if llm_result is not None:
        _render_llm_result(llm_result)

    console.print(
        "[dim]Scanner note: static regex heuristics with Unicode-normalised (NFKC) matching. "
        "Findings indicate risk patterns, not confirmed vulnerabilities. "
        "HIGH/CRITICAL labels reflect pattern severity, not detection certainty — "
        "review each finding before treating it as authoritative. "
        "Does not detect synonym substitution, indirect reference, or multi-turn attacks.[/dim]"
    )


def _render_multi_rich(
    scan_results: list[tuple[str, ScanResult, LLMAnalysisResult | None]],
    collected: CollectResult,
) -> None:
    total = len(scan_results)
    with_findings = sum(1 for _, sr, _ in scan_results if sr.findings)
    clean = total - with_findings

    summary = (
        f"[bold]{total}[/bold] files scanned  "
        f"[red]{with_findings} with findings[/red]  "
        f"[green]{clean} clean[/green]  "
        f"[dim]{collected.total_bytes:,} bytes[/dim]"
    )
    console.print(Panel(summary, title="Multi-File Scan Summary", border_style="blue"))

    for file_path, sr, lr in scan_results:
        if sr.findings:
            console.print(
                Panel(
                    format_scan_findings(sr),
                    title=f"[red]{file_path}[/red]  Risk: [bold]{sr.risk_level}[/bold]",
                    border_style="red",
                    expand=False,
                )
            )
        else:
            console.print(f"  [green]✓[/green]  [dim]{file_path}[/dim]")

        if lr is not None and not lr.skipped:
            _render_llm_result(lr)

    if collected.skipped_count:
        console.print(
            f"\n[dim]{collected.skipped_count} files skipped "
            f"(use --show-skipped to list them)[/dim]"
        )


def _render_llm_result(lr: LLMAnalysisResult) -> None:
    if lr.skipped:
        if lr.skip_reason not in ("llm_disabled", "privacy_mode"):
            console.print(f"  [yellow]LLM skipped:[/yellow] {lr.skip_reason}")
        return

    if not lr.findings:
        console.print(f"  [green]LLM:[/green] no semantic concerns  [dim](model: {lr.model})[/dim]")
        return

    for f in lr.findings:
        colour = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan", "INFO": "blue"}.get(
            f.severity, "white"
        )
        console.print(
            f"  [bold {colour}][LLM {f.severity}][/bold {colour}] [{f.category}] {f.message}"
        )
        if f.recommendation:
            console.print(f"    [dim]→ {f.recommendation}[/dim]")

    if lr.redaction_count:
        console.print(f"  [dim]Pre-send redaction: {lr.redaction_count} secret(s) replaced[/dim]")


def _render_skipped_table(collected: CollectResult) -> None:
    table = Table(title="Skipped Files", box=box.SIMPLE, show_header=True)
    table.add_column("File", style="dim")
    table.add_column("Reason", style="yellow")
    for sf in collected.skipped[:50]:  # cap display at 50 rows
        table.add_row(sf.path, sf.reason)
    if len(collected.skipped) > 50:
        table.add_row(f"… {len(collected.skipped) - 50} more …", "")
    console.print(table)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _output_or_write(text: str, out: str | None, force: bool) -> None:
    if out:
        _write_output(out, text, force)
    else:
        click.echo(text)


def _write_output(out: str, text: str, force: bool) -> None:
    try:
        safe_write_text(out, text, force=force)
        console.print(f"[dim]Results saved to {out}[/dim]")
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Exit code logic
# ---------------------------------------------------------------------------


def _exit_for_severity(
    scan_results: list[ScanResult],
    fail_on_severity: str | None,
    default_high_exit: bool = True,
) -> None:
    if fail_on_severity:
        threshold = fail_on_severity.upper()
        if _any_finding_at_or_above(scan_results, threshold):
            sys.exit(1)
        sys.exit(0)

    if default_high_exit and any(r.risk_level in ("CRITICAL", "HIGH") for r in scan_results):
        sys.exit(1)

    sys.exit(0)
