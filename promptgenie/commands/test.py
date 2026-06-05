import sys

import click
from rich.panel import Panel

from promptgenie.core.tester import run_test_suite
from promptgenie.renderers.rich import console


@click.command(name="test")
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

    status_color = "green" if result.passed else "red"
    status_label = "PASSED" if result.passed else "FAILED"
    console.print(
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
        console.print(f"\n  {icon}  [bold]{case.name}[/bold]")
        for assertion in case.assertions:
            if not assertion.passed:
                console.print(f"      [red]FAIL[/red]  {assertion.detail}")
                console.print(f"             [dim]actual: {assertion.actual}[/dim]")
            elif verbose:
                console.print(f"      [green]PASS[/green]  [dim]{assertion.detail}[/dim]")

    console.print()
    sys.exit(0 if result.passed else 1)
