"""graph_cmd.py — ``promptgenie graph`` command.

Renders the prompt dependency graph — how PromptSpecs and workflows depend on
their templates, target profiles, providers/models, policies, context sources,
and output schemas — as Mermaid, Graphviz DOT, or JSON.

Examples
--------
  promptgenie graph workflows/secure-login.workflow.yaml --format mermaid
  promptgenie graph specs/auth-review.promptgenie.yaml --format dot
  promptgenie graph --format json            # scan the whole project
  promptgenie graph --format mermaid --out graph.mmd
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from promptgenie.core.errors import EXIT_OK, EXIT_USAGE
from promptgenie.core.graph import GraphError, build_graph
from promptgenie.renderers.rich import diag_console


@click.command("graph")
@click.argument("files", nargs=-1, type=click.Path())
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["mermaid", "dot", "json"], case_sensitive=False),
    default="mermaid",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--root",
    default=".",
    type=click.Path(),
    show_default=True,
    help="Directory to scan when no FILES are given.",
)
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(),
    help="Write the graph to FILE instead of stdout.",
)
def graph_cmd(files: tuple[str, ...], output_format: str, root: str, out: str | None) -> None:
    """Render the prompt dependency graph.

    With one or more FILES, graphs those specs/workflows and their
    dependencies. With no FILES, every recognisable spec/workflow under --root
    is discovered and graphed.

    \b
    Examples:
      promptgenie graph workflows/secure-login.workflow.yaml --format mermaid
      promptgenie graph --format json | jq '.nodes[].kind'
      promptgenie graph --format dot --out graph.dot
    """
    try:
        graph = build_graph(list(files), root=root)
    except GraphError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    if not graph.nodes:
        where = ", ".join(files) if files else root
        diag_console.print(
            f"[yellow]No PromptSpecs or workflows found in[/yellow] {where}."
        )

    if output_format == "json":
        text = json.dumps(graph.to_json(), indent=2) + "\n"
    elif output_format == "dot":
        text = graph.to_dot()
    else:
        text = graph.to_mermaid()

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        diag_console.print(
            f"[green]✓[/green] Graph ({len(graph.nodes)} nodes, "
            f"{len(graph.edges)} edges) written to [bold]{out}[/bold]"
        )
    else:
        sys.stdout.write(text)
        sys.stdout.flush()

    raise SystemExit(EXIT_OK)
