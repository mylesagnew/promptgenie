"""tokens_cmd.py — ``promptgenie tokens`` read-only token inspector.

Reports a prompt's token count and the *potential* compression savings per
technique, without modifying anything. The read-only companion to
``promptgenie compress`` / ``optimize``.

Examples
--------
  promptgenie tokens prompt.md
  promptgenie tokens prompt.md --format json | jq '.combined.all'
  cat context.md | promptgenie tokens -
"""

from __future__ import annotations

import json
import sys

import click
import yaml

from promptgenie.core.compressor import (
    ALL_TECHNIQUES,
    DEFAULT_TECHNIQUES,
    compress,
)
from promptgenie.core.errors import EXIT_OK, EXIT_USAGE
from promptgenie.core.fileio import safe_read_text
from promptgenie.core.generator import estimate_tokens
from promptgenie.renderers.rich import console, diag_console, is_structured_mode


def _estimator_name() -> str:
    try:
        import tiktoken  # noqa: F401

        return "tiktoken"
    except Exception:
        return "heuristic (len/4)"


@click.command("tokens")
@click.argument("file", default="-", metavar="FILE|-")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "yaml"], case_sensitive=False),
    default="text",
    show_default=True,
)
def tokens_cmd(file: str, output_format: str) -> None:
    """Report token count and potential per-technique compression savings.

    Read-only: nothing is written or modified. Run ``promptgenie compress`` to
    actually apply the savings shown here.

    \b
    Examples:
      promptgenie tokens prompt.md
      promptgenie tokens prompt.md --format json | jq '.combined.all'
      cat context.md | promptgenie tokens -
    """
    try:
        text = safe_read_text(file)
    except (OSError, ValueError) as exc:
        diag_console.print(f"[red]Error:[/red] Cannot read {file!r}: {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    tokens = estimate_tokens(text)
    chars = len(text)

    # Each technique applied individually — "what would this one save?"
    per_technique = []
    for name in ALL_TECHNIQUES:
        result = compress(text, techniques=[name])
        per_technique.append(
            {
                "name": name,
                "tier": "default" if name in DEFAULT_TECHNIQUES else "aggressive",
                "tokens_saved": result.tokens_saved,
                "chars_saved": result.chars_before - result.chars_after,
                "occurrences": sum(t.occurrences for t in result.applied),
            }
        )

    default_combined = compress(text, techniques=DEFAULT_TECHNIQUES)
    all_combined = compress(text, techniques=ALL_TECHNIQUES)
    combined = {
        "default": {
            "tokens_saved": default_combined.tokens_saved,
            "tokens_after": default_combined.tokens_after,
            "percent": round(default_combined.ratio * 100, 1),
        },
        "all": {
            "tokens_saved": all_combined.tokens_saved,
            "tokens_after": all_combined.tokens_after,
            "percent": round(all_combined.ratio * 100, 1),
        },
    }

    if is_structured_mode(output_format):
        data = {
            "schema_version": "1.0",
            "source": file,
            "tokens": tokens,
            "chars": chars,
            "estimator": _estimator_name(),
            "techniques": per_technique,
            "combined": combined,
        }
        out = (
            yaml.dump(data, default_flow_style=False, sort_keys=False)
            if output_format == "yaml"
            else json.dumps(data, indent=2)
        )
        sys.stdout.write(out + "\n")
        raise SystemExit(EXIT_OK)

    # ---- human-readable report ----
    console.print(f"[bold]Token report[/bold] — {file}")
    console.print(
        f"  tokens: [cyan]{tokens}[/cyan]   chars: {chars}   "
        f"[dim]estimator: {_estimator_name()}[/dim]\n"
    )
    console.print(
        "  [bold]Potential savings by technique[/bold] [dim](applied individually)[/dim]:"
    )
    for t in per_technique:
        label = f"{t['name']:<22}"
        if t["tokens_saved"] or t["chars_saved"]:
            console.print(
                f"    {label} [green]−{t['tokens_saved']} tok[/green]  "
                f"[dim]({t['tier']}, {t['occurrences']} edit(s), −{t['chars_saved']} chars)[/dim]"
            )
        else:
            console.print(f"    [dim]{label} no effect ({t['tier']})[/dim]")
    d, a = combined["default"], combined["all"]
    console.print(
        f"\n  default tier (combined):    [green]−{d['tokens_saved']} tok "
        f"(−{d['percent']}%)[/green] → {d['tokens_after']}"
    )
    console.print(
        f"  all techniques (combined):  [green]−{a['tokens_saved']} tok "
        f"(−{a['percent']}%)[/green] → {a['tokens_after']}"
    )
    console.print(
        "\n  [dim]Inspection only — run [bold]promptgenie compress[/bold] to apply.[/dim]"
    )
    raise SystemExit(EXIT_OK)
