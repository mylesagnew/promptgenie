"""context.py — ``promptgenie context`` command group.

Commands
--------
  promptgenie context build    assemble context from sources and print it
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from promptgenie.core.context_builder import build_context
from promptgenie.core.errors import EXIT_USAGE, PromptGenieError
from promptgenie.core.spec import ContextSource
from promptgenie.renderers.rich import diag_console


@click.group("context", help="Assemble and inspect context sources.")
def context_group() -> None:
    pass


@context_group.command("build")
@click.option(
    "--file",
    "file_paths",
    multiple=True,
    metavar="PATH",
    help="Include a file as context (repeatable).",
)
@click.option(
    "--glob",
    "glob_patterns",
    multiple=True,
    metavar="PATTERN",
    help="Include files matching glob pattern (repeatable).",
)
@click.option("--stdin", "include_stdin", is_flag=True, help="Include stdin as a context source.")
@click.option(
    "--cmd",
    "commands",
    multiple=True,
    metavar="COMMAND",
    help="Run a shell command and include its stdout (repeatable).",
)
@click.option("--git-diff", "include_git_diff", is_flag=True, help="Include output of 'git diff'.")
@click.option(
    "--git-staged",
    "include_git_staged",
    is_flag=True,
    help="Include output of 'git diff --staged'.",
)
@click.option(
    "--url",
    "urls",
    multiple=True,
    metavar="URL",
    help="Fetch a URL and include its content (repeatable, requires --allow-url).",
)
@click.option("--allow-url", is_flag=True, help="Allow URL sources (policy-gated by default).")
@click.option(
    "--max-tokens",
    default=0,
    type=int,
    help="Token budget. Excess sources are trimmed. 0 = unlimited.",
)
@click.option(
    "--strategy",
    type=click.Choice(["manual", "newest", "smallest", "git-relevant"], case_sensitive=False),
    default="manual",
    show_default=True,
    help="Source ordering/trimming strategy.",
)
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(),
    help="Write assembled context to this file instead of stdout.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "yaml"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--manifest-only",
    is_flag=True,
    help="Print the source manifest (labels, hashes, token estimates) without the text.",
)
@click.option(
    "--compress",
    "compress_context",
    is_flag=True,
    help="Run the lossless compressor over the assembled context to save tokens.",
)
@click.option(
    "--compress-aggressive",
    is_flag=True,
    help="Compress with the aggressive techniques too (implies --compress).",
)
def context_build_cmd(
    file_paths: tuple[str, ...],
    glob_patterns: tuple[str, ...],
    include_stdin: bool,
    commands: tuple[str, ...],
    include_git_diff: bool,
    include_git_staged: bool,
    urls: tuple[str, ...],
    allow_url: bool,
    max_tokens: int,
    strategy: str,
    out: str | None,
    output_format: str,
    manifest_only: bool,
    compress_context: bool,
    compress_aggressive: bool,
) -> None:
    """Assemble context from one or more sources.

    \b
    Examples:
      promptgenie context build --glob "src/**/*.py" --max-tokens 8000
      promptgenie context build --git-diff --git-staged
      promptgenie context build --file README.md --out context.md
      promptgenie context build --git-diff --format json | jq '.manifest'
      git diff | promptgenie context build --stdin
    """
    sources: list[ContextSource] = []

    for fp in file_paths:
        sources.append(ContextSource(type="file", path=fp))
    for pat in glob_patterns:
        sources.append(ContextSource(type="glob", pattern=pat))
    if include_stdin:
        sources.append(ContextSource(type="stdin"))
    for cmd in commands:
        sources.append(ContextSource(type="cmd", command=cmd))
    if include_git_diff:
        sources.append(ContextSource(type="git_diff"))
    if include_git_staged:
        sources.append(ContextSource(type="git_staged"))
    for url in urls:
        sources.append(ContextSource(type="url", url=url))

    if not sources:
        diag_console.print(
            "[yellow]No sources specified.[/yellow] "
            "Use --file, --glob, --git-diff, --stdin, or --cmd."
        )
        raise SystemExit(EXIT_USAGE)

    try:
        manifest = build_context(
            sources,
            max_tokens=max_tokens,
            strategy=strategy,
            base_dir=Path.cwd(),
            no_url=not allow_url,
            compress=compress_context,
            compress_aggressive=compress_aggressive,
        )
    except PromptGenieError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(exc.code) from exc

    comp = manifest.compression
    if comp is not None and comp.changed:
        diag_console.print(
            f"[green]Compressed[/green] context "
            f"{comp.tokens_before} → {comp.tokens_after} tokens "
            f"([bold]-{comp.ratio:.0%}[/bold], {len(comp.applied)} technique(s))"
        )
    elif comp is not None:
        diag_console.print("[dim]Compression made no change to the assembled context.[/dim]")

    compression_obj = (
        {
            "tokens_before": comp.tokens_before,
            "tokens_after": comp.tokens_after,
            "tokens_saved": comp.tokens_saved,
            "ratio": round(comp.ratio, 4),
            "techniques": [t.name for t in comp.applied],
        }
        if comp is not None
        else None
    )

    if output_format == "json":
        output_obj = {
            "schema_version": "1.0",
            "total_tokens": manifest.total_tokens,
            "trimmed_count": manifest.trimmed_count,
            "compression": compression_obj,
            "manifest": [
                {
                    "label": e.label,
                    "source_type": e.source_type,
                    "path": e.path or None,
                    "sha256": e.sha256[:12],
                    "token_estimate": e.token_estimate,
                    "included": e.included,
                }
                for e in manifest.entries
            ],
            "text": manifest.text if not manifest_only else "",
        }
        text_out = json.dumps(output_obj, indent=2)
    elif output_format == "yaml":
        output_obj = {
            "schema_version": "1.0",
            "total_tokens": manifest.total_tokens,
            "trimmed_count": manifest.trimmed_count,
            "compression": compression_obj,
            "manifest": [
                {
                    "label": e.label,
                    "source_type": e.source_type,
                    "sha256": e.sha256[:12],
                    "token_estimate": e.token_estimate,
                    "included": e.included,
                }
                for e in manifest.entries
            ],
            "text": manifest.text if not manifest_only else "",
        }
        text_out = yaml.dump(output_obj, default_flow_style=False, sort_keys=False)
    else:
        if manifest_only:
            lines = [
                f"# Context manifest — {len(manifest.entries)} sources, "
                f"~{manifest.total_tokens} tokens\n"
            ]
            for e in manifest.entries:
                flag = "✓" if e.included else "✗"
                lines.append(
                    f"{flag}  [{e.source_type}] {e.label}  "
                    f"sha256:{e.sha256[:12]}  ~{e.token_estimate} tokens"
                )
            if manifest.trimmed_count:
                lines.append(f"\n({manifest.trimmed_count} source(s) trimmed by token budget)")
            text_out = "\n".join(lines)
        else:
            text_out = manifest.text

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text_out, encoding="utf-8")
        diag_console.print(
            f"[green]✓[/green] Context written to [bold]{out}[/bold] "
            f"(~{manifest.total_tokens} tokens)"
        )
        if manifest.trimmed_count:
            diag_console.print(
                f"[yellow]⚠[/yellow] {manifest.trimmed_count} source(s) trimmed by "
                f"--max-tokens {max_tokens}"
            )
    else:
        sys.stdout.write(text_out)
        if not text_out.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
