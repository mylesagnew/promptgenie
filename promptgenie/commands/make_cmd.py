"""make_cmd.py — ``promptgenie make`` command.

A small YAML task-graph batch runner: wire ``lint`` / ``scan`` / ``test`` /
``evaluate`` (or any shell command) into a dependency graph in
``promptgenie.make.yaml`` and run the requested targets in topological order,
with optional changed-file filtering and bounded parallelism.

Examples
--------
  promptgenie make                       # run every task
  promptgenie make ci                    # run 'ci' and its dependencies
  promptgenie make --target ci --parallel 4
  promptgenie make ci --changed --base-ref origin/main
  promptgenie make --list
  promptgenie make ci --dry-run
"""

from __future__ import annotations

import json
import sys

import click

from promptgenie.core.change_detector import _git_changed_files, _is_in_git_repo
from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.core.make import (
    DEFAULT_MAKEFILE,
    MakefileError,
    TaskResult,
    load_makefile,
    resolve_targets,
    run_makefile,
)
from promptgenie.renderers.rich import diag_console, is_structured_mode

_STATUS_STYLE = {
    "pass": "[green]✓ pass[/green]",
    "fail": "[red]✗ fail[/red]",
    "skipped": "[dim]– skip[/dim]",
    "dry-run": "[cyan]· plan[/cyan]",
}


@click.command("make")
@click.argument("targets", nargs=-1, metavar="[TARGET...]")
@click.option(
    "--file",
    "-f",
    "makefile",
    default=DEFAULT_MAKEFILE,
    show_default=True,
    type=click.Path(),
    help="Path to the makefile.",
)
@click.option(
    "--target",
    "target_opts",
    multiple=True,
    metavar="NAME",
    help="Target to run (repeatable). Combined with positional TARGETs.",
)
@click.option("--changed", is_flag=True, help="Skip tasks whose inputs did not change (git).")
@click.option(
    "--base-ref",
    default="origin/main",
    show_default=True,
    metavar="REF",
    help="Git ref to diff against for --changed.",
)
@click.option(
    "--parallel",
    "-p",
    default=1,
    show_default=True,
    type=int,
    metavar="N",
    help="Maximum number of tasks to run concurrently.",
)
@click.option(
    "--keep-going",
    "-k",
    is_flag=True,
    help="Continue running independent tasks after a failure.",
)
@click.option("--dry-run", "dry_run", is_flag=True, help="Print the plan without executing.")
@click.option("--list", "list_tasks", is_flag=True, help="List available tasks and exit.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
)
def make_cmd(
    targets: tuple[str, ...],
    makefile: str,
    target_opts: tuple[str, ...],
    changed: bool,
    base_ref: str,
    parallel: int,
    keep_going: bool,
    dry_run: bool,
    list_tasks: bool,
    output_format: str,
) -> None:
    """Run a YAML task graph (lint/scan/test/evaluate and any shell command).

    \b
    Define tasks in promptgenie.make.yaml:
      tasks:
        lint: { run: "promptgenie lint prompts/**/*.md", inputs: ["prompts/**/*.md"] }
        scan: { run: "promptgenie scan prompts/**/*.md", inputs: ["prompts/**/*.md"] }
        ci:   { needs: [lint, scan] }

    \b
    Examples:
      promptgenie make ci
      promptgenie make ci --parallel 4 --changed
      promptgenie make --list
    """
    try:
        mf = load_makefile(makefile)
    except MakefileError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    structured = is_structured_mode(output_format)
    requested = list(targets) + list(target_opts)

    if list_tasks:
        _list(mf, structured)
        raise SystemExit(EXIT_OK)

    # Resolve the changed-file set up front so we can report it.
    changed_files: list[str] | None = None
    if changed:
        if not _is_in_git_repo():
            diag_console.print("[red]Error:[/red] --changed requires a git repository.")
            raise SystemExit(EXIT_USAGE)
        changed_files = [str(p) for p in _git_changed_files(base_ref)]

    try:
        order = resolve_targets(mf, requested)
    except MakefileError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    if not structured and not dry_run:
        plan = " → ".join(order)
        diag_console.print(f"[bold]make[/bold] {plan}")

    on_complete = None if (structured or dry_run) else _live_reporter()

    run = run_makefile(
        mf,
        requested,
        changed=changed_files,
        parallel=parallel,
        keep_going=keep_going,
        dry_run=dry_run,
        on_complete=on_complete,
    )

    if structured:
        _emit_json(run.results, changed_files=changed_files)
    else:
        _report_summary(run.results, dry_run=dry_run)

    raise SystemExit(EXIT_OK if run.ok else EXIT_FAILURE)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _live_reporter():
    def report(result: TaskResult) -> None:
        badge = _STATUS_STYLE.get(result.status, result.status)
        suffix = ""
        if result.status == "pass":
            suffix = f" [dim]({result.duration_ms} ms)[/dim]"
        elif result.status == "fail":
            suffix = f" [dim](exit {result.exit_code}, {result.duration_ms} ms)[/dim]"
        elif result.status == "skipped" and result.reason:
            suffix = f" [dim]({result.reason})[/dim]"
        diag_console.print(f"  {badge}  {result.name}{suffix}")
        if result.status == "fail" and result.output:
            sys.stdout.write(result.output)
            if not result.output.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()

    return report


def _report_summary(results: list[TaskResult], *, dry_run: bool) -> None:
    if dry_run:
        diag_console.print("[bold]Plan[/bold] (dry run):")
        for r in results:
            badge = _STATUS_STYLE.get(r.status, r.status)
            cmds = "; ".join(r.commands) if r.commands else "[dim](no command)[/dim]"
            note = f" [dim]({r.reason})[/dim]" if r.reason else ""
            diag_console.print(f"  {badge}  {r.name}{note}\n      [dim]{cmds}[/dim]")
        return

    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skipped")
    total_ms = sum(r.duration_ms for r in results)
    parts = [f"[green]{passed} passed[/green]"]
    if failed:
        parts.append(f"[red]{failed} failed[/red]")
    if skipped:
        parts.append(f"[dim]{skipped} skipped[/dim]")
    diag_console.print(f"[bold]Done[/bold] — {', '.join(parts)} [dim]({total_ms} ms)[/dim]")


def _list(mf, structured: bool) -> None:
    if structured:
        data = {
            "schema_version": "1.0",
            "tasks": [
                {
                    "name": t.name,
                    "description": t.description,
                    "needs": t.needs,
                    "inputs": t.inputs,
                    "commands": t.run,
                }
                for t in mf.tasks.values()
            ],
        }
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        sys.stdout.flush()
        return
    diag_console.print("[bold]Tasks[/bold]")
    for t in mf.tasks.values():
        deps = f" [dim](needs: {', '.join(t.needs)})[/dim]" if t.needs else ""
        desc = f"  [dim]{t.description}[/dim]" if t.description else ""
        diag_console.print(f"  [bold]{t.name}[/bold]{deps}{desc}")


def _emit_json(results: list[TaskResult], *, changed_files: list[str] | None) -> None:
    data = {
        "schema_version": "1.0",
        "ok": not any(r.status == "fail" for r in results),
        "changed_filter": changed_files is not None,
        "tasks": [
            {
                "name": r.name,
                "status": r.status,
                "exit_code": r.exit_code,
                "duration_ms": r.duration_ms,
                "commands": r.commands,
                "reason": r.reason,
                "output": r.output,
            }
            for r in results
        ],
    }
    sys.stdout.write(json.dumps(data, indent=2) + "\n")
    sys.stdout.flush()
