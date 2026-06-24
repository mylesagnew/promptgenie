"""redact.py — ``promptgenie redact`` command.

Redacts secrets and PII from a prompt file (or stdin), replacing matches
with labelled placeholders such as [REDACTED:API_KEY].

Examples
--------
  promptgenie redact prompt.md
  promptgenie redact prompt.md --out redacted.md
  promptgenie redact prompt.md --categories secret
  promptgenie redact prompt.md --diff
  cat prompt.md | promptgenie redact -
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from promptgenie.core.errors import EXIT_OK, EXIT_USAGE, PromptGenieError
from promptgenie.core.fileio import safe_read_text
from promptgenie.core.redactor import redact
from promptgenie.renderers.rich import console, diag_console, is_structured_mode

_ALL_CATEGORIES = {"secret", "data-leakage"}


@click.command("redact")
@click.argument("file", default="-", metavar="FILE|-")
@click.option("--out", "-o", default=None, type=click.Path(),
              help="Write redacted output to FILE instead of stdout.")
@click.option("--categories", default=None, metavar="CAT[,CAT...]",
              help="Comma-separated categories to redact: secret, data-leakage. "
                   "Default: all redactable categories.")
@click.option("--diff", is_flag=True,
              help="Show a side-by-side summary of what was redacted instead of full output.")
@click.option("--format", "output_format",
              type=click.Choice(["text", "json", "yaml"], case_sensitive=False),
              default="text", show_default=True)
@click.option("--dry-run", "dry_run", is_flag=True,
              help="Show what would be redacted without writing output.")
def redact_cmd(
    file: str,
    out: str | None,
    categories: str | None,
    diff: bool,
    output_format: str,
    dry_run: bool,
) -> None:
    """Redact secrets and PII from a prompt file.

    Replaces detected secrets, tokens, and PII with labelled placeholders
    such as [REDACTED:API_KEY] or [REDACTED:EMAIL_ADDRESS].

    \b
    Examples:
      promptgenie redact prompt.md
      promptgenie redact prompt.md --out safe-prompt.md
      promptgenie redact prompt.md --diff
      promptgenie redact prompt.md --format json | jq '.replacements'
      cat prompt.md | promptgenie redact -
    """
    try:
        text = safe_read_text(file)
    except (OSError, ValueError) as exc:
        diag_console.print(f"[red]Error:[/red] Cannot read {file!r}: {exc}")
        raise SystemExit(EXIT_USAGE)

    effective_cats: set[str] | None = None
    if categories:
        effective_cats = {c.strip().lower() for c in categories.split(",")}
        invalid = effective_cats - _ALL_CATEGORIES
        if invalid:
            diag_console.print(
                f"[red]Unknown categories:[/red] {', '.join(sorted(invalid))}. "
                f"Valid: {', '.join(sorted(_ALL_CATEGORIES))}"
            )
            raise SystemExit(EXIT_USAGE)

    result = redact(text, categories=effective_cats)

    if is_structured_mode(output_format):
        data = {
            "schema_version": "1.0",
            "source": file,
            "count": result.count,
            "redacted_text": result.redacted_text,
            "replacements": [
                {
                    "rule_id": r.rule_id,
                    "placeholder": r.placeholder,
                    "original_length": len(r.original),
                    "start": r.start,
                    "end": r.end,
                }
                for r in result.replacements
            ],
        }
        if output_format == "yaml":
            text_out = yaml.dump(data, default_flow_style=False, sort_keys=False)
        else:
            text_out = json.dumps(data, indent=2)

        if out and not dry_run:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(text_out, encoding="utf-8")
            diag_console.print(f"[green]✓[/green] Redacted output written to {out}")
        else:
            sys.stdout.write(text_out + "\n")
        raise SystemExit(EXIT_OK)

    if diff or dry_run:
        if result.count == 0:
            diag_console.print("[green]✓[/green] No secrets or PII detected — nothing to redact.")
            raise SystemExit(EXIT_OK)
        diag_console.print(f"[bold]Redaction summary[/bold] — {result.count} replacement(s):\n")
        for i, r in enumerate(result.replacements, 1):
            orig_display = r.original if len(r.original) <= 40 else r.original[:40] + "…"
            diag_console.print(
                f"  {i:2}. [red]{orig_display!r}[/red] → [green]{r.placeholder}[/green]"
                f"  [dim]({r.rule_id})[/dim]"
            )
        if dry_run:
            raise SystemExit(EXIT_OK)
        # With --diff, still write output unless --dry-run was set
        text_out = result.redacted_text
    else:
        text_out = result.redacted_text

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text_out, encoding="utf-8")
        diag_console.print(
            f"[green]✓[/green] Redacted {result.count} item(s) → [bold]{out}[/bold]"
        )
    else:
        sys.stdout.write(text_out)
        if not text_out.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
