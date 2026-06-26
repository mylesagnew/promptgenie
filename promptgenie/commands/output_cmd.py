"""output_cmd.py — ``promptgenie output`` command group.

Subcommands
-----------
  output repair FILE --schema S   coerce malformed output to fit a JSON Schema

Examples
--------
  promptgenie output repair response.txt --schema schema.json
  promptgenie output repair response.txt --schema schema.json --out fixed.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.core.fileio import safe_read_text
from promptgenie.core.output_contract import (
    OutputContractError,
    load_schema,
    repair_payload,
)
from promptgenie.renderers.rich import diag_console, is_structured_mode

_PAYLOAD_FORMATS = ["auto", "json", "yaml", "markdown", "text", "code"]


def _infer_format(file: str, override: str) -> str:
    if override != "auto":
        return override
    suffix = Path(file).suffix.lower()
    if suffix in (".yaml", ".yml"):
        return "yaml"
    return "json"


@click.group("output", help="Work with structured model output.")
def output_group() -> None:
    pass


@output_group.command("repair")
@click.argument("file", default="-", metavar="FILE|-")
@click.option(
    "--schema",
    "schema_path",
    required=True,
    type=click.Path(),
    help="JSON Schema file (.json or .yaml) the output should satisfy.",
)
@click.option(
    "--input-format",
    "input_format",
    type=click.Choice(_PAYLOAD_FORMATS, case_sensitive=False),
    default="auto",
    show_default=True,
    help="How to parse the response payload (auto: infer from file suffix).",
)
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(),
    help="Write the repaired payload to FILE instead of stdout.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Report format for the summary printed to stderr / stdout.",
)
def output_repair_cmd(
    file: str,
    schema_path: str,
    input_format: str,
    out: str | None,
    output_format: str,
) -> None:
    """Coerce malformed output so it satisfies a JSON Schema.

    Extracts JSON embedded in prose, coerces scalar types, and fills missing
    required fields from their schema ``default`` (or a type-appropriate zero).
    The repaired JSON is written to --out or stdout; a summary of repairs and
    any residual errors goes to stderr. Exits 0 if the result is valid, 1 if it
    still violates the schema after repair, 2 on a usage error.

    \b
    Examples:
      promptgenie output repair response.txt --schema schema.json
      promptgenie output repair resp.txt --schema s.json --out fixed.json
    """
    try:
        schema = load_schema(schema_path)
    except OutputContractError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    try:
        text = safe_read_text(file)
    except (OSError, ValueError) as exc:
        diag_console.print(f"[red]Error:[/red] Cannot read {file!r}: {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    fmt = _infer_format(file, input_format)
    result = repair_payload(text, schema, fmt)

    if result.obj is None:
        # Nothing parseable to repair.
        if is_structured_mode(output_format):
            sys.stdout.write(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": file,
                        "valid": False,
                        "repairs": result.repairs,
                        "errors": result.errors,
                    },
                    indent=2,
                )
                + "\n"
            )
        else:
            diag_console.print(f"[red]✗[/red] Could not repair {file!r}: {result.errors[0]}")
        raise SystemExit(EXIT_USAGE)

    # Emit the repaired payload.
    if is_structured_mode(output_format):
        sys.stdout.write(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source": file,
                    "valid": result.valid,
                    "repairs": result.repairs,
                    "errors": result.errors,
                    "repaired": result.obj,
                },
                indent=2,
            )
            + "\n"
        )
    else:
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(result.repaired_text + "\n", encoding="utf-8")
            diag_console.print(f"[green]✓[/green] Repaired payload written to [bold]{out}[/bold]")
        else:
            sys.stdout.write(result.repaired_text + "\n")
            sys.stdout.flush()

        if result.repairs:
            diag_console.print(f"[cyan]{len(result.repairs)} repair(s) applied:[/cyan]")
            for r in result.repairs:
                diag_console.print(f"  [cyan]•[/cyan] {r}")
        if result.valid:
            diag_console.print("[green]✓[/green] Output now conforms to the schema.")
        else:
            diag_console.print(
                f"[yellow]⚠[/yellow] {len(result.errors)} issue(s) remain after repair:"
            )
            for e in result.errors:
                diag_console.print(f"  [yellow]•[/yellow] {e}")

    raise SystemExit(EXIT_OK if result.valid else EXIT_FAILURE)
