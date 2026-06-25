"""validate_output.py — ``promptgenie validate-output`` command.

Validates a model response (file or stdin) against a JSON Schema.

Examples
--------
  promptgenie validate-output response.json --schema output.schema.json
  promptgenie run spec.yaml --tee out.json && \\
      promptgenie validate-output out.json --schema output.schema.json
  cat response.json | promptgenie validate-output - --schema s.json --format json
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
    parse_payload,
    validate_payload,
)
from promptgenie.renderers.rich import console, diag_console, is_structured_mode

_PAYLOAD_FORMATS = ["auto", "json", "yaml", "markdown", "text", "code"]


def _infer_format(file: str, override: str) -> str:
    if override != "auto":
        return override
    suffix = Path(file).suffix.lower()
    if suffix in (".yaml", ".yml"):
        return "yaml"
    if suffix in (".md", ".markdown"):
        return "markdown"
    return "json"


@click.command("validate-output")
@click.argument("file", default="-", metavar="FILE|-")
@click.option(
    "--schema",
    "schema_path",
    required=True,
    type=click.Path(),
    help="JSON Schema file (.json or .yaml) to validate against.",
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
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Report format.",
)
def validate_output_cmd(
    file: str, schema_path: str, input_format: str, output_format: str
) -> None:
    """Validate a model response against a JSON Schema.

    Exits 0 when the payload is valid, 1 when it violates the schema, and 2 on
    a usage error (unreadable file/schema or unparseable payload).

    \b
    Examples:
      promptgenie validate-output response.json --schema output.schema.json
      cat resp.json | promptgenie validate-output - --schema s.json --format json
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
    obj, parse_err = parse_payload(text, fmt)
    if parse_err is not None:
        if is_structured_mode(output_format):
            sys.stdout.write(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": file,
                        "valid": False,
                        "parse_error": parse_err,
                        "errors": [],
                    },
                    indent=2,
                )
                + "\n"
            )
        else:
            diag_console.print(f"[red]Error:[/red] Could not parse {file!r} as {fmt}: {parse_err}")
        raise SystemExit(EXIT_USAGE)

    errors = validate_payload(obj, schema)

    if is_structured_mode(output_format):
        sys.stdout.write(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source": file,
                    "format": fmt,
                    "valid": not errors,
                    "errors": errors,
                },
                indent=2,
            )
            + "\n"
        )
    elif errors:
        console.print(f"[red]✗[/red] {file} is [bold]invalid[/bold] — {len(errors)} error(s):")
        for e in errors:
            console.print(f"  [red]•[/red] {e}")
    else:
        console.print(f"[green]✓[/green] {file} conforms to the schema.")

    raise SystemExit(EXIT_FAILURE if errors else EXIT_OK)
