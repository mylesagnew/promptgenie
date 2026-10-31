import sys

import click
from rich.panel import Panel

from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie.core.errors import EXIT_OK, EXIT_TEST, EXIT_USAGE
from promptgenie.core.tester import run_test_suite
from promptgenie.renderers import rich as renderer


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
        renderer.diag_console.print(f"[yellow]Warning:[/yellow] could not load config: {exc}")
        return PromptGenieConfig(), None


@click.command(name="test")
@click.argument("test_file", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Show all assertions, not just failures.")
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(),
    help="Path to .promptgenie.yaml config file.",
)
@click.option("--no-config", is_flag=True, help="Ignore .promptgenie.yaml; use default settings.")
def test_cmd(test_file, verbose, config_path, no_config):
    """Run a prompt test suite (.prompt-test.yaml)."""
    cfg, cfg_file = _resolve_config(config_path, no_config)
    try:
        with renderer.console.status("[bold blue]Running tests…"):
            result = run_test_suite(test_file, config=cfg)
    except FileNotFoundError as e:
        renderer.diag_console.print(f"[red]Error:[/red] {e}")
        sys.exit(EXIT_USAGE)

    renderer.console.print()
    if cfg_file:
        renderer.diag_console.print(f"[dim]Config: {cfg_file}[/dim]")

    status_color = "green" if result.passed else "red"
    status_label = "PASSED" if result.passed else "FAILED"
    renderer.console.print(
        Panel(
            f"[bold {status_color}]{status_label}[/bold {status_color}]  "
            f"{result.pass_count}/{result.total} tests passed"
            + (f"\n[dim]{result.description}[/dim]" if result.description else ""),
            title=f"Test Suite  [dim]{test_file}[/dim]",
            border_style=status_color,
        )
    )

    for case in result.cases:
        icon = "[green]✓[/green]" if case.passed else "[red]✗[/red]"
        renderer.console.print(f"\n  {icon}  [bold]{case.name}[/bold]")
        for assertion in case.assertions:
            if not assertion.passed:
                renderer.console.print(f"      [red]FAIL[/red]  {assertion.detail}")
                renderer.console.print(f"             [dim]actual: {assertion.actual}[/dim]")
            elif verbose:
                renderer.console.print(f"      [green]PASS[/green]  [dim]{assertion.detail}[/dim]")

    renderer.console.print()
    # Exit 5 (EXIT_TEST) for test assertion failures, 0 for pass
    sys.exit(EXIT_OK if result.passed else EXIT_TEST)
