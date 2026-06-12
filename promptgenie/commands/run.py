"""run.py — ``promptgenie run`` command.

End-to-end PromptSpec execution:
  load spec → resolve vars → build context → lint/scan/policy gate
  → render prompt → send to provider → stream response → persist run

Examples
--------
  promptgenie run my-prompt.yaml
  promptgenie run my-prompt.yaml --dry-run
  promptgenie run my-prompt.yaml --stream --provider ollama --model llama3
  promptgenie run my-prompt.yaml --var env=prod --vars secrets.yaml
  promptgenie run my-prompt.yaml --tee output.md
  promptgenie run my-prompt.yaml --no-input --format ndjson
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from promptgenie.core.errors import (
    EXIT_OK,
    EXIT_USAGE,
    PromptGenieError,
    handle_error,
)
from promptgenie.core.run_engine import RunEvent, run_spec
from promptgenie.core.spec import PromptSpec, load_spec
from promptgenie.core.trust import add_trust, is_trusted, spec_requires_trust
from promptgenie.renderers.rich import diag_console


def _describe_sources(spec: PromptSpec) -> list[str]:
    """Human-readable one-liners for the host-touching context sources."""
    host_types = {"cmd", "file", "glob", "env", "url"}
    lines: list[str] = []
    for s in spec.context or []:
        if s.type not in host_types:
            continue
        detail = s.command or s.path or s.pattern or s.var or s.url or ""
        lines.append(f"  - [{s.type}] {detail}")
    return lines


def _trust_gate(
    *,
    spec: PromptSpec,
    spec_file: str,
    no_input: bool,
    trust_spec: bool,
    assume_yes: bool,
) -> None:
    """Block execution of an untrusted spec's host-touching context sources (S-2)."""
    if not spec_requires_trust(spec):
        return
    spec_path = Path(spec_file)
    if is_trusted(spec_path):
        return

    # Explicit non-interactive trust grant.
    if trust_spec or assume_yes:
        add_trust(spec_path)
        return

    interactive = sys.stdin.isatty() and not no_input
    if not interactive:
        handle_error(
            PromptGenieError(
                "Spec has host-touching context sources (cmd/file/glob/env/url) "
                "and is not trusted. Re-run with --trust to record it as trusted, "
                "or run interactively to be prompted.",
                code=EXIT_USAGE,
            )
        )

    diag_console.print(
        "[yellow]⚠ This spec contains context sources that run on your host:[/yellow]"
    )
    for line in _describe_sources(spec):
        diag_console.print(f"[yellow]{line}[/yellow]")
    if not click.confirm("Trust this spec and its context sources?", default=False):
        handle_error(PromptGenieError("Spec not trusted; aborting.", code=EXIT_USAGE))
    add_trust(spec_path)


@click.command("run")
@click.argument("spec_file", type=click.Path(exists=True))
# Variable flags
@click.option(
    "--var",
    "var_list",
    multiple=True,
    metavar="KEY=VALUE",
    help="Inline variable override (repeatable). Example: --var env=prod",
)
@click.option(
    "--vars",
    "vars_file",
    default=None,
    metavar="FILE",
    help="YAML/JSON file of variable values. Merged with --var flags.",
)
@click.option(
    "--env-prefix",
    default="PG_",
    show_default=True,
    help="Environment variable prefix for auto-binding.",
)
@click.option(
    "--no-input",
    is_flag=True,
    help="Never prompt interactively — fail if a variable is unresolved.",
)
# Execution flags
@click.option(
    "--dry-run",
    is_flag=True,
    help="Resolve variables and build context but do not call the provider.",
)
@click.option(
    "--stream/--no-stream",
    default=None,
    help="Stream response tokens as they arrive (default: from spec).",
)
@click.option(
    "--require-clean", is_flag=True, default=None, help="Abort if the git working tree is dirty."
)
@click.option(
    "--provider",
    "provider_override",
    default=None,
    help="Override provider name from providers.yaml.",
)
@click.option(
    "--model",
    "model_override",
    default=None,
    help="Override model name (e.g. gpt-4o, claude-opus-4-5, llama3).",
)
@click.option(
    "--timeout",
    default=None,
    type=int,
    metavar="SECONDS",
    help="Abort provider call after this many seconds.",
)
@click.option(
    "--no-history", is_flag=True, default=None, help="Do not persist this run to history."
)
# Context flags
@click.option(
    "--max-context-tokens",
    default=0,
    type=int,
    help="Token budget for context assembly. 0 = unlimited.",
)
@click.option(
    "--context-strategy",
    type=click.Choice(["manual", "newest", "smallest", "git-relevant"], case_sensitive=False),
    default="manual",
    show_default=True,
    help="Strategy for trimming context to the token budget.",
)
@click.option(
    "--allow-url", is_flag=True, help="Allow URL-type context sources (policy-gated by default)."
)
@click.option(
    "--allow-sensitive-env",
    is_flag=True,
    help="Permit env-type context sources that name credential-like variables "
    "(KEY/SECRET/TOKEN/...). Blocked by default to prevent secret exfiltration.",
)
@click.option(
    "--trust",
    "trust_spec",
    is_flag=True,
    help="Trust this spec's context sources without prompting (records the spec as trusted).",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Assume yes to prompts (also trusts the spec's context sources).",
)
@click.option(
    "--allow-secrets",
    is_flag=True,
    help="Override the secrets gate and send the prompt even if secrets are detected. "
    "Use with caution — secrets in prompts may be logged by providers.",
)
# Output flags
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "ndjson"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format: text (default) or ndjson (machine-readable events).",
)
@click.option(
    "--tee",
    "tee_file",
    default=None,
    type=click.Path(),
    help="Write final response to this file while streaming to stdout.",
)
@click.option(
    "--show-context",
    is_flag=True,
    help="Print the assembled context before sending (dry-run style).",
)
def run_cmd(
    spec_file: str,
    var_list: tuple[str, ...],
    vars_file: str | None,
    env_prefix: str,
    no_input: bool,
    dry_run: bool,
    stream: bool | None,
    require_clean: bool | None,
    provider_override: str | None,
    model_override: str | None,
    timeout: int | None,
    no_history: bool | None,
    max_context_tokens: int,
    context_strategy: str,
    allow_url: bool,
    allow_sensitive_env: bool,
    trust_spec: bool,
    assume_yes: bool,
    allow_secrets: bool,
    output_format: str,
    tee_file: str | None,
    show_context: bool,
) -> None:
    """Execute a PromptSpec end-to-end.

    Loads SPEC_FILE, resolves variables, assembles context, runs lint/scan/policy
    gate, renders the prompt, and sends it to the configured provider.

    \b
    Examples:
      promptgenie run my-prompt.yaml
      promptgenie run my-prompt.yaml --dry-run --show-context
      promptgenie run my-prompt.yaml --provider ollama --model llama3 --stream
      promptgenie run my-prompt.yaml --var env=prod --tee response.md
      promptgenie run my-prompt.yaml --format ndjson | jq 'select(.event=="done")'
    """
    ndjson_mode = output_format == "ndjson"

    def _on_token(token: str) -> None:
        if ndjson_mode:
            print(json.dumps({"event": "token", "text": token}), flush=True)
        else:
            # Write directly — bypass Rich so it's raw/streamable
            sys.stdout.write(token)
            sys.stdout.flush()

    def _on_event(event: RunEvent) -> None:
        if ndjson_mode and event.event != "token":
            print(event.to_ndjson(), flush=True)

    try:
        spec = load_spec(spec_file)
    except PromptGenieError as exc:
        handle_error(exc)

    # ---- spec trust gate (S-2) ----
    # Specs with host-touching context sources (cmd/file/glob/env/url) must be
    # explicitly trusted before their sources run, to defend against a cloned
    # malicious repo executing code on first invocation.
    _trust_gate(
        spec=spec,
        spec_file=spec_file,
        no_input=no_input,
        trust_spec=trust_spec,
        assume_yes=assume_yes,
    )

    if show_context and spec.context:
        from promptgenie.core.context_builder import build_context

        base_dir = Path(spec_file).parent
        manifest = build_context(
            spec.context,
            max_tokens=max_context_tokens,
            strategy=context_strategy,
            base_dir=base_dir,
            no_url=not allow_url,
            allow_sensitive_env=allow_sensitive_env,
        )
        diag_console.print("[bold]Context manifest:[/bold]")
        for entry in manifest.entries:
            status = "✓" if entry.included else "✗ (trimmed)"
            diag_console.print(
                f"  [{entry.source_type}] {entry.label}  ~{entry.token_estimate} tokens  {status}"
            )
        diag_console.print(f"[dim]Total: ~{manifest.total_tokens} tokens[/dim]\n")

    if ndjson_mode:
        print(json.dumps({"event": "start", "spec": spec_file, "dry_run": dry_run}), flush=True)

    try:
        result = run_spec(
            spec,
            cli_vars=list(var_list),
            vars_file=vars_file,
            env_prefix=env_prefix,
            no_input=no_input,
            dry_run=dry_run,
            stream=stream,
            require_clean=require_clean,
            provider_override=provider_override,
            model_override=model_override,
            timeout=timeout,
            no_history=no_history if no_history else None,
            max_context_tokens=max_context_tokens,
            context_strategy=context_strategy,
            allow_url=allow_url,
            allow_sensitive_env=allow_sensitive_env,
            allow_secrets=allow_secrets,
            on_token=_on_token,
            on_event=_on_event,
            tee_file=Path(tee_file) if tee_file else None,
        )
    except PromptGenieError as exc:
        if ndjson_mode:
            print(json.dumps({"event": "error", "message": str(exc), "code": exc.code}), flush=True)
        handle_error(exc)

    # ---- post-run output ----
    if not ndjson_mode and not dry_run and result.response:
        # Streaming already printed tokens; add newline separator
        sys.stdout.write("\n")
        sys.stdout.flush()

    if result.dry_run:
        if ndjson_mode:
            print(
                json.dumps(
                    {
                        "event": "done",
                        "status": "dry_run",
                        "resolved_vars": dict(result.resolved_vars.items()),
                    }
                ),
                flush=True,
            )
        else:
            diag_console.print("\n[yellow]Dry run complete.[/yellow]")
            if result.resolved_vars:
                diag_console.print("[dim]Resolved variables:[/dim]")
                for k, v in result.resolved_vars.items():
                    display_v = "***" if "secret" in k.lower() else v
                    diag_console.print(f"  {k} = {display_v}")
            if result.context_manifest:
                m = result.context_manifest
                diag_console.print(
                    f"[dim]Context: {len(m.entries)} sources, ~{m.total_tokens} tokens[/dim]"
                )
        raise SystemExit(EXIT_OK)

    if ndjson_mode:
        print(
            json.dumps(
                {
                    "event": "done",
                    "status": result.status,
                    "run_id": result.run_id,
                    "duration_s": result.duration_s,
                    "response_length": len(result.response),
                }
            ),
            flush=True,
        )
    else:
        diag_console.print(
            f"\n[dim]run_id={result.run_id}  status={result.status}  {result.duration_s:.1f}s[/dim]"
        )
        if tee_file:
            diag_console.print(f"[dim]Response written to: {tee_file}[/dim]")
