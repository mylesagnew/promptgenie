"""interactive.py — guided menu mode for PromptGenie."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.text import Text

console = Console()

_MENU = [
    ("Generate a new prompt", "generate"),
    ("Improve / adapt an existing prompt", "adapt"),
    ("Lint a prompt", "lint"),
    ("Scan a prompt for security risks", "scan"),
    ("Compare two prompts", "diff"),
    ("Run prompt tests", "test"),
    ("Manage context packs", "pack"),
    ("Generate a workflow", "workflow"),
    ("List targets / templates", "list"),
    ("Exit", "exit"),
]


def _show_menu() -> None:
    lines = Text()
    for i, (label, _) in enumerate(_MENU, 1):
        lines.append(f"  {i}. {label}\n", style="white" if i < len(_MENU) else "dim")
    console.print(Panel(lines, title="[bold cyan]PromptGenie[/bold cyan]", border_style="cyan"))


def _run_choice(ctx: click.Context, choice: int) -> bool:
    """Return False to exit the loop."""
    _, cmd = _MENU[choice - 1]

    if cmd == "exit":
        console.print("[dim]Goodbye.[/dim]")
        return False

    if cmd == "generate":
        task = Prompt.ask("[cyan]Task description[/cyan]")
        target = Prompt.ask("[cyan]Target[/cyan]", default="claude-code")
        ctx.invoke(ctx.obj["generate"], task=task, target=target)

    elif cmd == "adapt":
        path = Prompt.ask("[cyan]Prompt file path[/cyan]")
        target = Prompt.ask("[cyan]New target[/cyan]", default="claude-code")
        ctx.invoke(ctx.obj["adapt"], prompt_file=path, target=target)

    elif cmd == "lint":
        path = Prompt.ask("[cyan]Prompt file path[/cyan]")
        ctx.invoke(ctx.obj["lint"], prompt_file=path)

    elif cmd == "scan":
        path = Prompt.ask("[cyan]Prompt file path[/cyan]")
        ctx.invoke(ctx.obj["scan"], prompt_file=path)

    elif cmd == "diff":
        a = Prompt.ask("[cyan]First prompt file[/cyan]")
        b = Prompt.ask("[cyan]Second prompt file[/cyan]")
        ctx.invoke(ctx.obj["diff"], prompt_a=a, prompt_b=b)

    elif cmd == "test":
        path = Prompt.ask("[cyan]Test suite file (.prompt-test.yaml)[/cyan]")
        ctx.invoke(ctx.obj["test"], test_file=path)

    elif cmd == "pack":
        console.print("[dim]Run [bold]promptgenie pack --help[/bold] for pack sub-commands.[/dim]")

    elif cmd == "workflow":
        path = Prompt.ask("[cyan]Workflow file (.workflow.yaml)[/cyan]")
        ctx.invoke(ctx.obj["workflow"], workflow_file=path)

    elif cmd == "list":
        console.print("\n[bold]Targets:[/bold]")
        ctx.invoke(ctx.obj["list_targets"])
        console.print("\n[bold]Templates:[/bold]")
        ctx.invoke(ctx.obj["list_templates"])

    return True


@click.command("interactive")
@click.pass_context
def interactive_cmd(ctx: click.Context) -> None:
    """Launch the guided interactive menu."""
    # Resolve sibling commands from the root group.
    root_cmd = ctx.find_root().command
    assert isinstance(root_cmd, click.Group), "interactive must be used inside a click.Group"
    ctx.obj = {
        "generate": root_cmd.get_command(ctx, "generate"),
        "adapt": root_cmd.get_command(ctx, "adapt"),
        "lint": root_cmd.get_command(ctx, "lint"),
        "scan": root_cmd.get_command(ctx, "scan"),
        "diff": root_cmd.get_command(ctx, "diff"),
        "test": root_cmd.get_command(ctx, "test"),
        "workflow": root_cmd.get_command(ctx, "workflow"),
        "list_targets": root_cmd.get_command(ctx, "list-targets"),
        "list_templates": root_cmd.get_command(ctx, "list-templates"),
    }

    console.print(
        "\n[bold cyan]Welcome to PromptGenie[/bold cyan] — "
        "secure prompt engineering for AI agents.\n"
    )

    while True:
        _show_menu()
        try:
            choice = IntPrompt.ask(
                "[cyan]Choose[/cyan]",
                default=1,
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Interrupted.[/dim]")
            break

        if choice < 1 or choice > len(_MENU):
            console.print(f"[red]Please enter a number between 1 and {len(_MENU)}.[/red]")
            continue

        try:
            if not _run_choice(ctx, choice):
                break
        except click.exceptions.Exit:
            pass
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Error:[/red] {exc}")

        console.print()
