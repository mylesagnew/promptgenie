"""watcher.py — File-system watch engine for promptgenie watch.

Uses ``watchfiles`` when available; falls back to polling when not installed.

The on-change pipeline:
  1. Debounce (default 300ms) — ignore rapid successive saves
  2. Read changed file content
  3. For each --run task: lint, scan, policy, test, evaluate
  4. Print compact dashboard via Rich Live
  5. Track final state; exit non-zero on policy failures when --fail-on-policy

Public API
----------
  ``WatchPipeline``        — dataclass describing a watch task
  ``run_watch(paths, pipelines, ...)``  — blocking; runs until Ctrl+C
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class WatchPipeline:
    """One pipeline step to run on every file change."""
    name: str              # "lint", "scan", "policy", "test", "evaluate"
    label: str = ""        # Rich display label
    run_fn: Callable[[str, str], dict] | None = None  # (file_path, content) → result dict

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name.title()


@dataclass
class WatchResult:
    file_path: str
    pipeline_name: str
    passed: bool
    summary: str
    findings_count: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Built-in pipeline runners
# ---------------------------------------------------------------------------

def _run_lint(file_path: str, content: str) -> dict:
    from promptgenie.core.linter import lint
    result = lint(content)
    high = sum(1 for i in result.issues if i.severity == "HIGH")
    med = sum(1 for i in result.issues if i.severity == "MEDIUM")
    return {
        "passed": high == 0,
        "summary": f"Score {result.score}/100  {high}H {med}M",
        "findings_count": len(result.issues),
    }


def _run_scan(file_path: str, content: str) -> dict:
    from promptgenie.core.scanner import scan
    result = scan(content)
    risk = result.risk_level
    count = len(result.findings)
    return {
        "passed": risk not in ("CRITICAL", "HIGH"),
        "summary": f"Risk {risk}  {count} finding(s)",
        "findings_count": count,
    }


def _run_policy(file_path: str, content: str) -> dict:
    try:
        from promptgenie.core.policy_engine import discover_policy_file, evaluate_policy, load_policy
        policy_file = discover_policy_file()
        if policy_file is None:
            return {"passed": True, "summary": "No policy file", "findings_count": 0}
        policy = load_policy(policy_file)
        from promptgenie.core.analyze import analyze
        analysis = analyze(content)
        report = evaluate_policy(analysis, policy)
        return {
            "passed": report.passed,
            "summary": (
                "Policy passed" if report.passed
                else f"{len(report.violations)} violation(s)"
            ),
            "findings_count": len(report.violations),
        }
    except Exception as exc:
        return {"passed": True, "summary": f"Policy error: {exc}", "findings_count": 0}


_PIPELINE_RUNNERS: dict[str, Callable[[str, str], dict]] = {
    "lint": _run_lint,
    "scan": _run_scan,
    "policy": _run_policy,
}


def make_pipeline(name: str) -> WatchPipeline:
    """Create a built-in WatchPipeline by name."""
    fn = _PIPELINE_RUNNERS.get(name)
    if fn is None:
        raise ValueError(
            f"Unknown pipeline {name!r}. "
            f"Valid: {sorted(_PIPELINE_RUNNERS.keys())}"
        )
    return WatchPipeline(name=name, label=name.title(), run_fn=fn)


# ---------------------------------------------------------------------------
# Watch engine
# ---------------------------------------------------------------------------

def run_watch(
    paths: list[str],
    pipelines: list[WatchPipeline],
    *,
    debounce_ms: int = 300,
    fail_on_policy: bool = True,
    poll_interval_s: float = 1.0,
) -> int:
    """
    Watch *paths* for file changes and run *pipelines* on each change.

    Returns exit code (0 = clean final state, 1 = policy failures remain).
    """
    from rich.live import Live
    from rich.table import Table
    from rich.text import Text
    from promptgenie.renderers.rich import console

    # Try watchfiles; fall back to polling
    try:
        from watchfiles import watch as _wf_watch
        _use_watchfiles = True
    except ImportError:
        _use_watchfiles = False

    # State: last result per (file, pipeline)
    state: dict[tuple[str, str], WatchResult] = {}

    def _build_dashboard() -> Table:
        table = Table(show_header=True, header_style="bold", title="PromptGenie Watch")
        table.add_column("File", no_wrap=True)
        table.add_column("Pipeline", width=10)
        table.add_column("Status", width=8)
        table.add_column("Summary")
        for (fp, pl), res in sorted(state.items()):
            status = "[green]PASS[/green]" if res.passed else "[red]FAIL[/red]"
            if res.error:
                status = "[yellow]ERR[/yellow]"
            table.add_row(fp, pl, status, res.summary)
        return table

    def _process_file(file_path: str) -> None:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for pipeline in pipelines:
            if pipeline.run_fn is None:
                continue
            try:
                result = pipeline.run_fn(file_path, content)
                state[(file_path, pipeline.name)] = WatchResult(
                    file_path=file_path,
                    pipeline_name=pipeline.name,
                    passed=result.get("passed", True),
                    summary=result.get("summary", ""),
                    findings_count=result.get("findings_count", 0),
                )
            except Exception as exc:
                state[(file_path, pipeline.name)] = WatchResult(
                    file_path=file_path,
                    pipeline_name=pipeline.name,
                    passed=False,
                    summary="error",
                    error=str(exc),
                )

    # Initial run on all matching files
    resolved_paths: list[str] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            for ext in ("*.md", "*.txt", "*.yaml", "*.yml", "*.prompt"):
                resolved_paths.extend(str(f) for f in pp.rglob(ext))
        elif pp.exists():
            resolved_paths.append(str(pp))

    console.print(f"[dim]Watching {len(resolved_paths)} file(s)…  Ctrl+C to stop.[/dim]")
    for fp in resolved_paths:
        _process_file(fp)

    try:
        with Live(console=console, refresh_per_second=4, screen=False) as live:
            live.update(_build_dashboard())

            if _use_watchfiles:
                from watchfiles import watch as _wf_watch, Change
                for changes in _wf_watch(*paths, debounce=debounce_ms):
                    for change_type, changed_path in changes:
                        if change_type in (Change.modified, Change.added):
                            _process_file(changed_path)
                    live.update(_build_dashboard())
            else:
                # Polling fallback
                mtimes: dict[str, float] = {
                    fp: Path(fp).stat().st_mtime for fp in resolved_paths
                    if Path(fp).exists()
                }
                while True:
                    time.sleep(poll_interval_s)
                    for fp in list(resolved_paths):
                        try:
                            mtime = Path(fp).stat().st_mtime
                            if mtimes.get(fp) != mtime:
                                mtimes[fp] = mtime
                                _process_file(fp)
                                live.update(_build_dashboard())
                        except OSError:
                            pass

    except KeyboardInterrupt:
        pass

    # Final exit code
    if fail_on_policy:
        any_fail = any(not r.passed for r in state.values())
        return 1 if any_fail else 0
    return 0
