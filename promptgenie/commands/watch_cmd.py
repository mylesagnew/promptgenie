"""watch_cmd.py — ``promptgenie watch`` command.

Watches a directory or file for changes and re-runs configured pipelines
on every save.  Requires ``watchfiles`` for inotify/kqueue watching;
falls back to 1-second polling when not installed.

Examples
--------
  promptgenie watch prompts/
  promptgenie watch prompts/ --run lint --run scan
  promptgenie watch prompts/auth.md --run lint --run policy
  promptgenie watch . --debounce 500 --fail-on-policy
"""

from __future__ import annotations

import click

from promptgenie.core.errors import EXIT_FAILURE
from promptgenie.renderers.rich import console, diag_console


@click.command("watch")
@click.argument("paths", nargs=-1, required=True)
@click.option(
    "--run",
    "pipelines",
    multiple=True,
    type=click.Choice(["lint", "scan", "policy"], case_sensitive=False),
    default=["lint", "scan"],
    help="Pipelines to run on each change (repeatable). Default: lint scan.",
)
@click.option(
    "--debounce",
    default=300,
    type=int,
    show_default=True,
    help="Debounce delay in milliseconds (requires watchfiles).",
)
@click.option(
    "--fail-on-policy/--no-fail-on-policy",
    default=True,
    show_default=True,
    help="Exit 1 if final state has any pipeline failure.",
)
@click.option(
    "--poll-interval",
    default=1.0,
    type=float,
    show_default=True,
    help="Polling interval in seconds (used when watchfiles not available).",
)
def watch_cmd(
    paths: tuple[str, ...],
    pipelines: tuple[str, ...],
    debounce: int,
    fail_on_policy: bool,
    poll_interval: float,
) -> None:
    """Watch files for changes and re-run lint/scan/policy automatically.

    Requires: pip install 'promptgenie[watch]'  (for real-time inotify support)
    Falls back to polling (1-second interval) without watchfiles.

    \b
    Examples:
      promptgenie watch prompts/
      promptgenie watch prompts/ --run lint --run scan --run policy
      promptgenie watch prompts/auth.md --fail-on-policy
    """
    from importlib.util import find_spec

    from promptgenie.core.watcher import make_pipeline, run_watch

    if find_spec("watchfiles") is not None:
        console.print("[dim]watchfiles: real-time watching active.[/dim]")
    else:
        console.print(
            "[yellow]watchfiles not installed — using polling (1s interval).[/yellow]\n"
            "[dim]Install with: pip install 'promptgenie[watch]'[/dim]"
        )

    pipeline_objs = []
    for name in pipelines or ("lint", "scan"):
        try:
            pipeline_objs.append(make_pipeline(name))
        except ValueError as exc:
            diag_console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(EXIT_FAILURE) from None

    exit_code = run_watch(
        list(paths),
        pipeline_objs,
        debounce_ms=debounce,
        fail_on_policy=fail_on_policy,
        poll_interval_s=poll_interval,
    )
    raise SystemExit(exit_code)
