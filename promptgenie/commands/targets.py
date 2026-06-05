import click
from rich import box
from rich.table import Table

from promptgenie.core.generator import list_targets, list_templates
from promptgenie.renderers.rich import console


@click.command("list-targets")
def list_targets_cmd():
    """List all available target AI tool profiles."""
    targets = list_targets()
    table = Table(title="Available Target Profiles", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Category", style="dim")
    table.add_column("Strengths", style="dim")
    for t in targets:
        strengths = ", ".join(t["strengths"][:3])
        table.add_row(t["id"], t["name"], t["category"], strengths)
    console.print(table)


@click.command("list-templates")
def list_templates_cmd():
    """List all available prompt templates."""
    templates = list_templates()
    table = Table(title="Available Templates", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Category", style="dim")
    table.add_column("Description", style="dim")
    for t in templates:
        table.add_row(t["id"], t["name"], t["category"], t["description"])
    console.print(table)
