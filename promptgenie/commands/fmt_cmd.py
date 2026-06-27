"""fmt_cmd.py — ``promptgenie fmt`` command.

A deterministic formatter for Markdown prompt files and PromptSpec YAML, in the
spirit of ``gofmt`` / ``black`` / ``prettier``: one canonical layout so reviews
stay focused on content rather than whitespace.

Behaviour
---------
* **File arguments** are formatted **in place** by default (atomic write); only
  files that change are touched. ``--check`` writes nothing and exits 1 if any
  file would change (CI-safe). ``--diff`` prints a unified diff instead.
* **Stdin** (``-`` or no argument) is formatted to **stdout**, so ``fmt`` slots
  into a pipe. ``--check`` / ``--diff`` behave the same.

Examples
--------
  promptgenie fmt prompts/*.md
  promptgenie fmt prompts/auth.promptgenie.yaml
  promptgenie fmt --check prompts/
  promptgenie fmt --diff prompt.md
  cat prompt.md | promptgenie fmt -
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

import click

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.core.fileio import safe_read_text, safe_write_text
from promptgenie.core.formatter import FormatResult, detect_file_type, format_text
from promptgenie.renderers.rich import diag_console, is_structured_mode


@click.command("fmt")
@click.argument("files", nargs=-1, metavar="FILE...|-")
@click.option(
    "--check",
    is_flag=True,
    help="Don't write. Exit 1 if any file would be reformatted (CI-safe).",
)
@click.option(
    "--diff",
    "show_diff",
    is_flag=True,
    help="Print a unified diff of the changes instead of writing.",
)
@click.option(
    "--lang",
    type=click.Choice(["auto", "markdown", "yaml"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Force the document type. 'auto' detects by extension (stdin → markdown).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Report format. 'json' emits a machine-readable summary to stdout.",
)
def fmt_cmd(
    files: tuple[str, ...],
    check: bool,
    show_diff: bool,
    lang: str,
    output_format: str,
) -> None:
    """Format Markdown prompts and PromptSpec YAML into a canonical layout.

    \b
    Markdown: trim trailing whitespace, collapse blank-line runs, normalise ATX
      headings, pad one blank line around headings, single final newline. Fenced
      code blocks are preserved byte-for-byte.
    YAML: the same whitespace normalisation plus canonical key ordering (matching
      the PromptSpec field order). Comments are preserved when ruamel.yaml is
      installed (promptgenie[fmt]); otherwise commented files keep their key
      order and only whitespace is normalised.

    \b
    Examples:
      promptgenie fmt prompts/*.md
      promptgenie fmt --check prompts/
      promptgenie fmt --diff prompt.md
      cat prompt.md | promptgenie fmt -
    """
    targets = list(files) if files else ["-"]
    paths = _expand(targets)

    results: list[tuple[str, FormatResult]] = []
    diffs: list[str] = []
    structured = is_structured_mode(output_format)

    for label in paths:
        try:
            text = safe_read_text(label)
        except (OSError, ValueError) as exc:
            diag_console.print(f"[red]Error:[/red] Cannot read {label!r}: {exc}")
            raise SystemExit(EXIT_USAGE) from exc

        file_type = lang if lang != "auto" else detect_file_type(label)
        result = format_text(text, file_type=file_type)
        results.append((label, result))

        if show_diff and result.changed:
            diffs.append(_unified_diff(label, result.original_text, result.formatted_text))

        # Write changes in place for real files (never for stdin, never on --check/--diff).
        if not check and not show_diff and not structured and label != "-" and result.changed:
            safe_write_text(label, result.formatted_text, force=True)

    if structured:
        _emit_json(results, check=check, wrote=not (check or show_diff))
        # JSON mode still applies in-place writes unless --check/--diff.
        if not check and not show_diff:
            for label, result in results:
                if label != "-" and result.changed:
                    safe_write_text(label, result.formatted_text, force=True)
        raise SystemExit(_exit_code(results, check))

    if show_diff:
        if diffs:
            sys.stdout.write("\n".join(diffs))
            sys.stdout.flush()
        raise SystemExit(_exit_code(results, check))

    if check:
        _report_check(results)
        raise SystemExit(_exit_code(results, check))

    # Default text mode: stdin → stdout; files → written in place above.
    stdin_results = [(label, r) for label, r in results if label == "-"]
    if stdin_results:
        for _label, result in stdin_results:
            sys.stdout.write(result.formatted_text)
            if result.formatted_text and not result.formatted_text.endswith("\n"):
                sys.stdout.write("\n")
        sys.stdout.flush()

    _report_writes(results)
    raise SystemExit(EXIT_OK)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FMT_EXTS = (".md", ".markdown", ".mdown", ".mkd", ".yaml", ".yml")


def _expand(targets: list[str]) -> list[str]:
    """Expand directory arguments to the formattable files they contain.

    ``-`` and plain file paths pass through unchanged; a directory is walked
    recursively for files with a recognised prompt/spec extension.
    """
    out: list[str] = []
    for t in targets:
        if t == "-":
            out.append(t)
            continue
        p = Path(t)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in _FMT_EXTS:
                    out.append(str(f))
        else:
            out.append(t)
    return out


def _unified_diff(label: str, before: str, after: str) -> str:
    name = "<stdin>" if label == "-" else label
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{name}",
        tofile=f"b/{name}",
    )
    return "".join(diff)


def _exit_code(results: list[tuple[str, FormatResult]], check: bool) -> int:
    if check and any(r.changed for _, r in results):
        return EXIT_FAILURE
    return EXIT_OK


def _report_check(results: list[tuple[str, FormatResult]]) -> None:
    changed = [(label, r) for label, r in results if r.changed]
    for label, r in changed:
        name = "<stdin>" if label == "-" else label
        rules = ", ".join(f"{x.name}×{x.occurrences}" for x in r.rules)
        diag_console.print(f"[yellow]would reformat[/yellow] {name}  [dim]{rules}[/dim]")
    n = len(results)
    if changed:
        diag_console.print(
            f"[yellow]{len(changed)}[/yellow] of {n} file(s) would be reformatted."
        )
    else:
        diag_console.print(f"[green]✓[/green] {n} file(s) already formatted.")


def _report_writes(results: list[tuple[str, FormatResult]]) -> None:
    written = [label for label, r in results if label != "-" and r.changed]
    if written:
        for label in written:
            diag_console.print(f"[green]✓[/green] formatted {label}")
        diag_console.print(f"[green]{len(written)}[/green] file(s) reformatted.")
    elif any(label != "-" for label, _ in results):
        diag_console.print("[green]✓[/green] all file(s) already formatted.")


def _emit_json(
    results: list[tuple[str, FormatResult]],
    *,
    check: bool,
    wrote: bool,
) -> None:
    files = []
    for label, r in results:
        entry = {
            "path": "<stdin>" if label == "-" else label,
            "file_type": r.file_type,
            "changed": r.changed,
            "rules": [{"name": x.name, "occurrences": x.occurrences} for x in r.rules],
        }
        if label == "-":
            entry["formatted_text"] = r.formatted_text
        files.append(entry)
    data = {
        "schema_version": "1.0",
        "mode": "check" if check else ("write" if wrote else "diff"),
        "files": files,
        "changed_count": sum(1 for _, r in results if r.changed),
        "total": len(results),
    }
    sys.stdout.write(json.dumps(data, indent=2) + "\n")
    sys.stdout.flush()
