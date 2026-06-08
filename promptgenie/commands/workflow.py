import sys

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.workflow import WorkflowValidationError, generate_workflow, save_workflow
from promptgenie.renderers.rich import console


@click.command(name="workflow")
@click.argument("workflow_file", type=click.Path(exists=True))
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(),
    help="Directory to save individual step prompts (one file per step).",
)
@click.option("--step", "-s", default=None, type=int, help="Show only a specific step number.")
@click.option("--summary", is_flag=True, help="Show workflow summary only — no prompt content.")
@click.option(
    "--best-effort",
    is_flag=True,
    help=(
        "Fall back to built-in defaults when a profile or context pack referenced in the "
        "workflow file is not found, instead of aborting with an error. Without this flag, "
        "unknown profile or pack names are fatal errors."
    ),
)
def workflow_cmd(workflow_file, out, step, summary, best_effort):
    """Generate a staged prompt chain from a .workflow.yaml file."""
    with console.status("[bold blue]Building workflow…"):
        try:
            result = generate_workflow(workflow_file, best_effort=best_effort)
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            console.print("[dim]Use --best-effort to fall back to built-in defaults.[/dim]")
            sys.exit(1)
        except WorkflowValidationError as e:
            console.print(f"[red]Workflow validation error:[/red] {e}")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

    console.print()

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

    steps_to_show = result.steps
    if step is not None:
        steps_to_show = [rs for rs in result.steps if rs.step_number == step]
        if not steps_to_show:
            console.print(f"[red]Step {step} not found.[/red]")
            sys.exit(1)

    for rs in steps_to_show:
        gate_label = "  [yellow][APPROVAL GATE][/yellow]" if rs.step.requires_approval else ""
        console.print(
            Panel(
                rs.prompt_text,
                title=f"Step {rs.step_number}/{rs.total_steps} — {rs.step.name}{gate_label}  [dim]{rs.token_estimate} tokens[/dim]",
                border_style="blue",
            )
        )

    if out:
        saved = save_workflow(result, out)
        console.print(f"\n[green]Saved {len(saved)} step prompt(s) to {out}/[/green]")
        for p in saved:
            console.print(f"  [dim]{p.name}[/dim]")
