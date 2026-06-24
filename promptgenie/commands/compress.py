"""compress.py — ``promptgenie compress`` / ``promptgenie optimize`` command.

Shrinks the token footprint of a prompt or context file (or stdin) using
PromptGenie's native, dependency-free compression engine — content-routed
techniques inspired by headroom (JSON compaction, whitespace/structure,
build-log de-duplication). Same content, fewer tokens.

Examples
--------
  promptgenie compress prompt.md
  promptgenie compress prompt.md --out smaller.md
  promptgenie compress prompt.md --max-tokens 4000
  promptgenie compress prompt.md --aggressive --diff
  promptgenie compress prompt.md --format json | jq '.tokens_saved'
  cat context.md | promptgenie compress -
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from promptgenie.core.compressor import (
    AGGRESSIVE_TECHNIQUES,
    ALL_TECHNIQUES,
    DEFAULT_TECHNIQUES,
    TECHNIQUES,
    UnknownTechniqueError,
    compress,
)
from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.core.fileio import safe_read_text
from promptgenie.renderers.rich import diag_console, is_structured_mode


def _build_command(name: str) -> click.Command:
    @click.command(name)
    @click.argument("file", default="-", metavar="FILE|-")
    @click.option(
        "--out",
        "-o",
        default=None,
        type=click.Path(),
        help="Write compressed output to FILE instead of stdout.",
    )
    @click.option(
        "--max-tokens",
        "max_tokens",
        default=None,
        type=int,
        metavar="N",
        help="Target token budget. Enables every technique and exits 1 "
        "if the result still exceeds N tokens.",
    )
    @click.option(
        "--techniques",
        default=None,
        metavar="T[,T...]",
        help="Comma-separated technique names to run (overrides tiers). "
        f"Available: {', '.join(ALL_TECHNIQUES)}.",
    )
    @click.option(
        "--aggressive",
        is_flag=True,
        help="Include the aggressive (mildly lossy) techniques on top of defaults.",
    )
    @click.option(
        "--list-techniques",
        "list_techniques",
        is_flag=True,
        help="List available compression techniques and exit.",
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json", "yaml"], case_sensitive=False),
        default="text",
        show_default=True,
    )
    @click.option("--diff", is_flag=True, help="Print a per-technique savings summary to stderr.")
    @click.option(
        "--dry-run",
        "dry_run",
        is_flag=True,
        help="Report savings without writing or emitting compressed text.",
    )
    def _cmd(
        file: str,
        out: str | None,
        max_tokens: int | None,
        techniques: str | None,
        aggressive: bool,
        list_techniques: bool,
        output_format: str,
        diff: bool,
        dry_run: bool,
    ) -> None:
        """Compress a prompt or context file to use fewer tokens.

        Runs content-routed structural techniques (JSON compaction, whitespace
        and blank-line collapse, build-log de-duplication) that reduce token
        count without changing the meaning of the prompt.

        \b
        Examples:
          promptgenie compress prompt.md
          promptgenie compress prompt.md --out smaller.md
          promptgenie compress prompt.md --max-tokens 4000
          promptgenie compress prompt.md --aggressive --diff
          cat context.md | promptgenie compress -
        """
        if list_techniques:
            _print_techniques()
            raise SystemExit(EXIT_OK)

        # Resolve the technique selection.
        selected: list[str] | None
        if techniques:
            selected = [t.strip() for t in techniques.split(",") if t.strip()]
        elif aggressive:
            selected = ALL_TECHNIQUES
        else:
            selected = None  # default tier (or all, when --max-tokens is set)

        try:
            text = safe_read_text(file)
        except (OSError, ValueError) as exc:
            diag_console.print(f"[red]Error:[/red] Cannot read {file!r}: {exc}")
            raise SystemExit(EXIT_USAGE) from exc

        try:
            result = compress(text, techniques=selected, max_tokens=max_tokens)
        except UnknownTechniqueError as exc:
            diag_console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(EXIT_USAGE) from exc

        pct = round(result.ratio * 100, 1)

        if is_structured_mode(output_format):
            data = {
                "schema_version": "1.0",
                "source": file,
                "tokens_before": result.tokens_before,
                "tokens_after": result.tokens_after,
                "tokens_saved": result.tokens_saved,
                "ratio": round(result.ratio, 4),
                "percent_saved": pct,
                "chars_before": result.chars_before,
                "chars_after": result.chars_after,
                "budget_met": result.budget_met,
                "techniques": [
                    {"name": t.name, "occurrences": t.occurrences, "chars_saved": t.chars_saved}
                    for t in result.applied
                ],
            }
            if not dry_run:
                data["compressed_text"] = result.compressed_text
            out_text = (
                yaml.dump(data, default_flow_style=False, sort_keys=False)
                if output_format == "yaml"
                else json.dumps(data, indent=2)
            )
            if out and not dry_run:
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(out_text, encoding="utf-8")
                diag_console.print(f"[green]✓[/green] Report written to {out}")
            else:
                sys.stdout.write(out_text + "\n")
            raise SystemExit(_exit_for(result))

        # ---- Human-readable (text) mode ----
        if diff or dry_run:
            _print_summary(file, result, pct)

        if not dry_run:
            out_text = result.compressed_text
            if out:
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(out_text, encoding="utf-8")
                diag_console.print(
                    f"[green]✓[/green] Compressed {result.tokens_before} → "
                    f"{result.tokens_after} tokens (−{pct}%) → [bold]{out}[/bold]"
                )
            else:
                sys.stdout.write(out_text)
                if not out_text.endswith("\n"):
                    sys.stdout.write("\n")
                sys.stdout.flush()

        raise SystemExit(_exit_for(result))

    return _cmd


def _exit_for(result) -> int:
    if result.budget_met is False:
        return EXIT_FAILURE
    return EXIT_OK


def _print_techniques() -> None:
    diag_console.print("[bold]Compression techniques[/bold]\n")
    for name in ALL_TECHNIQUES:
        tech = TECHNIQUES[name]
        tier = "[yellow]aggressive[/yellow]" if tech.aggressive else "[green]default[/green]"
        diag_console.print(f"  [bold]{name}[/bold]  {tier}\n    [dim]{tech.description}[/dim]")
    diag_console.print(f"\n[dim]Default tier: {', '.join(DEFAULT_TECHNIQUES)}[/dim]")
    diag_console.print(f"[dim]Aggressive tier: {', '.join(AGGRESSIVE_TECHNIQUES)}[/dim]")


def _print_summary(file: str, result, pct: float) -> None:
    diag_console.print(
        f"[bold]Compression summary[/bold] — {file}\n"
        f"  tokens: {result.tokens_before} → {result.tokens_after} "
        f"([green]−{result.tokens_saved}, −{pct}%[/green])\n"
        f"  chars:  {result.chars_before} → {result.chars_after}"
    )
    if result.budget_met is False:
        diag_console.print("  [red]⚠ token budget not met[/red]")
    elif result.budget_met is True:
        diag_console.print("  [green]✓ within token budget[/green]")
    if not result.applied:
        diag_console.print("  [dim]No applicable techniques — already compact.[/dim]")
        return
    diag_console.print("  techniques applied:")
    for t in result.applied:
        diag_console.print(
            f"    • {t.name}: {t.occurrences} edit(s), {t.chars_saved} char(s) saved"
        )


compress_cmd = _build_command("compress")
optimize_cmd = _build_command("optimize")
