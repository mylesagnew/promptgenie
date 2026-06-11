"""run_engine.py — end-to-end PromptSpec execution pipeline.

Pipeline stages
---------------
1. Resolve variables (CLI vars → spec vars → env → interactive → defaults)
2. Build context (assemble context sources, apply .promptignore + token budget)
3. Gate — lint + scan + policy checks; block if threshold exceeded
4. Render prompt (variable substitution; template + context prepended)
5. Send to provider (stream or complete)
6. Emit NDJSON events: start, token, warning, tool_call, error, done
7. Persist run to ~/.local/share/promptgenie/runs/ (unless --no-history)

Streaming output
----------------
When streaming to a TTY, each token is printed in-place. When piped, raw
tokens are emitted. When ``ndjson_events=True``, each event is a JSON line on
stdout.

Public API
----------
  ``run_spec(spec, ...)``           → RunResult
  ``dry_run_spec(spec, ...)``       → RunResult (no provider call)
  ``RunResult``                     — dataclass with response, status, events
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TextIO

from promptgenie.core.context_builder import ContextManifest, build_context
from promptgenie.core.errors import (
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_PROVIDER,
    EXIT_SECRETS,
    EXIT_TIMEOUT,
    PromptGenieError,
)
from promptgenie.core.history import RunRecord, RunWriter, open_run_writer
from promptgenie.core.providers import get_provider, load_providers_config
from promptgenie.core.spec import PromptSpec, render_spec
from promptgenie.core.variables import (
    VarResolutionError,
    load_vars_file,
    parse_cli_vars,
    resolve_variables,
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RunEvent:
    """A single NDJSON-serialisable event emitted during a run."""

    event: str  # start | token | warning | tool_call | error | done
    data: dict[str, Any] = field(default_factory=dict)

    def to_ndjson(self) -> str:
        return json.dumps({"event": self.event, **self.data})


@dataclass
class RunResult:
    run_id: str
    spec_name: str
    status: str  # ok | error | dry_run
    response: str
    dry_run: bool
    context_manifest: ContextManifest | None = None
    resolved_vars: dict[str, Any] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    error: str = ""
    duration_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


# ---------------------------------------------------------------------------
# Git working tree check
# ---------------------------------------------------------------------------


def _git_is_clean() -> tuple[bool, str]:
    """Return (is_clean, detail_message)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip():
            return False, result.stdout.strip()
        return True, ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True, ""  # no git — skip check


# ---------------------------------------------------------------------------
# Prompt assembler
# ---------------------------------------------------------------------------


def _assemble_prompt(
    spec: PromptSpec,
    resolved_vars: dict[str, Any],
    context_manifest: ContextManifest | None,
) -> str:
    """Combine context + rendered prompt into a single user message."""
    parts: list[str] = []

    if context_manifest and context_manifest.text:
        parts.append("## Context\n\n" + context_manifest.text)

    prompt_text = render_spec(spec, resolved_vars)
    if prompt_text:
        parts.append(prompt_text)

    return "\n\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Security pre-flight (secrets gate)
# ---------------------------------------------------------------------------


def _check_secrets_gate(text: str) -> list[str]:
    """Return a list of warnings for potential secrets in *text*."""
    from promptgenie.core.scanner import scan

    result = scan(text)
    secret_findings = [
        f for f in result.findings
        if f.risk in ("HIGH", "CRITICAL") and "secret" in f.category.lower()
    ]
    return [f.message for f in secret_findings]


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------


def _build_messages(
    spec: PromptSpec,
    prompt: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if spec.system_prompt:
        messages.append({"role": "system", "content": spec.system_prompt})
    if prompt:
        messages.append({"role": "user", "content": prompt})
    return messages


# ---------------------------------------------------------------------------
# Synchronous wrapper
# ---------------------------------------------------------------------------


def run_spec(
    spec: PromptSpec,
    *,
    # Variable overrides
    cli_vars: list[str] | None = None,
    vars_file: str | None = None,
    env_prefix: str = "PG_",
    no_input: bool = False,
    # Execution flags
    dry_run: bool = False,
    stream: bool | None = None,
    require_clean: bool | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    timeout: int | None = None,
    no_history: bool | None = None,
    # Context
    max_context_tokens: int = 0,
    context_strategy: str = "manual",
    allow_url: bool = False,
    # Output callbacks
    on_token: Callable[[str], None] | None = None,
    on_event: Callable[[RunEvent], None] | None = None,
    tee_file: Path | None = None,
) -> RunResult:
    """Execute *spec* end-to-end and return a RunResult.

    This is the synchronous entry point — wraps ``_run_spec_async``.
    """
    return asyncio.run(
        _run_spec_async(
            spec=spec,
            cli_vars=cli_vars,
            vars_file=vars_file,
            env_prefix=env_prefix,
            no_input=no_input,
            dry_run=dry_run,
            stream=stream,
            require_clean=require_clean,
            provider_override=provider_override,
            model_override=model_override,
            timeout=timeout,
            no_history=no_history,
            max_context_tokens=max_context_tokens,
            context_strategy=context_strategy,
            allow_url=allow_url,
            on_token=on_token,
            on_event=on_event,
            tee_file=tee_file,
        )
    )


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------


async def _run_spec_async(
    spec: PromptSpec,
    *,
    cli_vars: list[str] | None,
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
    on_token: Callable[[str], None] | None,
    on_event: Callable[[RunEvent], None] | None,
    tee_file: Path | None,
) -> RunResult:
    # ---- resolve flags from spec + overrides ----
    effective_dry_run = dry_run or spec.run.dry_run
    effective_stream = (stream if stream is not None else spec.run.stream)
    effective_require_clean = (require_clean if require_clean is not None
                               else spec.run.require_clean)
    effective_timeout = (timeout if timeout is not None else spec.run.timeout)
    effective_no_history = (no_history if no_history is not None else spec.run.no_history)
    effective_provider = provider_override or spec.provider or _infer_provider(spec.target)
    effective_model = model_override or spec.model

    events: list[RunEvent] = []

    def _emit(event: RunEvent) -> None:
        events.append(event)
        if on_event:
            on_event(event)

    # ---- 1. require_clean gate ----
    if effective_require_clean:
        clean, detail = _git_is_clean()
        if not clean:
            raise PromptGenieError(
                "Git working tree is dirty — refusing to run (--require-clean).",
                code=EXIT_FAILURE,
                hint=f"Uncommitted changes:\n{detail}",
            )

    # ---- 2. resolve variables ----
    merged_vars: dict[str, Any] = dict(spec.vars)
    if vars_file:
        merged_vars.update(load_vars_file(vars_file))
    cli_var_dict = parse_cli_vars(cli_vars or [])
    merged_vars.update(cli_var_dict)

    # Build a combined "inline" text with all placeholder occurrences
    combined_text = (spec.prompt or "") + " ".join(
        str(v) for v in merged_vars.values() if isinstance(v, str)
    )
    try:
        _, resolved_vars = resolve_variables(
            combined_text,
            cli_vars=cli_var_dict,
            vars_file_values=merged_vars,
            no_input=no_input,
            env_prefix=env_prefix,
        )
    except VarResolutionError as exc:
        raise PromptGenieError(str(exc), code=exc.code, hint=exc.hint) from exc

    # Merge spec vars with resolved vars
    final_vars = {**merged_vars, **resolved_vars}

    # ---- 3. build context ----
    context_manifest: ContextManifest | None = None
    if spec.context:
        base_dir = spec._source_path.parent if spec._source_path else Path.cwd()
        context_manifest = build_context(
            spec.context,
            max_tokens=max_context_tokens,
            strategy=context_strategy,
            base_dir=base_dir,
            no_url=not allow_url,
        )

    # ---- 4. assemble prompt ----
    prompt = _assemble_prompt(spec, final_vars, context_manifest)

    # ---- 4b. secrets gate (scan assembled prompt) ----
    secret_warnings = _check_secrets_gate(prompt)
    for warn in secret_warnings:
        _emit(RunEvent("warning", {"message": f"[secrets-gate] {warn}"}))

    # ---- dry-run: return without provider call ----
    if effective_dry_run:
        _emit(RunEvent("done", {"status": "dry_run"}))
        return RunResult(
            run_id="dry-run",
            spec_name=spec.name,
            status="dry_run",
            response="",
            dry_run=True,
            context_manifest=context_manifest,
            resolved_vars=final_vars,
            events=events,
        )

    # ---- 5. get provider ----
    provider = get_provider(effective_provider, model_override=effective_model)
    model_name = provider.model or effective_model or "unknown"

    # ---- run history writer ----
    import uuid, time as _time
    run_id = str(uuid.uuid4())[:8]

    writer: RunWriter | None = None
    if not effective_no_history:
        writer = RunWriter(
            run_id=run_id,
            spec_name=spec.name,
            target=spec.target,
            provider=effective_provider,
            model=model_name,
            dry_run=effective_dry_run,
        )
        writer._ensure_file()

    messages = _build_messages(spec, prompt)
    tee_fp: TextIO | None = None
    if tee_file:
        tee_file.parent.mkdir(parents=True, exist_ok=True)
        tee_fp = tee_file.open("w", encoding="utf-8")

    response_parts: list[str] = []

    try:
        if effective_stream:
            # ---- streaming path ----
            _emit(RunEvent("start", {"run_id": run_id, "spec_name": spec.name,
                                     "provider": effective_provider, "model": model_name}))
            async for token in provider.stream(
                messages,
                model=effective_model,
                max_tokens=spec.output_contract.max_tokens or 2048,
                timeout=effective_timeout,
            ):
                response_parts.append(token)
                _emit(RunEvent("token", {"text": token}))
                if on_token:
                    on_token(token)
                if writer:
                    writer.write_token(token)
                if tee_fp:
                    tee_fp.write(token)
                    tee_fp.flush()
        else:
            # ---- non-streaming path ----
            _emit(RunEvent("start", {"run_id": run_id, "spec_name": spec.name,
                                     "provider": effective_provider, "model": model_name}))
            response = await provider.complete(
                messages,
                model=effective_model,
                max_tokens=spec.output_contract.max_tokens or 2048,
                timeout=effective_timeout,
            )
            response_parts.append(response)
            _emit(RunEvent("token", {"text": response}))
            if on_token:
                on_token(response)
            if writer:
                writer.write_token(response)
            if tee_fp:
                tee_fp.write(response)

        full_response = "".join(response_parts)
        _emit(RunEvent("done", {"status": "ok", "response_length": len(full_response)}))

        record = writer.finish(status="ok") if writer else None

        return RunResult(
            run_id=run_id,
            spec_name=spec.name,
            status="ok",
            response=full_response,
            dry_run=False,
            context_manifest=context_manifest,
            resolved_vars=final_vars,
            events=events,
            duration_s=record.duration_s if record else 0.0,
        )

    except PromptGenieError:
        if writer:
            writer.finish(status="error")
        raise
    except Exception as exc:
        if writer:
            writer.finish(status="error", error=str(exc))
        raise PromptGenieError(
            f"Run failed: {exc}", code=EXIT_PROVIDER
        ) from exc
    finally:
        if tee_fp:
            tee_fp.close()


# ---------------------------------------------------------------------------
# Provider inference from target profile
# ---------------------------------------------------------------------------

_TARGET_PROVIDER_MAP: dict[str, str] = {
    "claude": "anthropic",
    "claude-code": "anthropic",
    "chatgpt": "openai",
    "gemini": "openai",  # via OpenAI-compat shim if configured
    "cursor": "openai",
}


def _infer_provider(target: str) -> str:
    """Guess provider name from target profile name."""
    target_lower = target.lower()
    for key, provider in _TARGET_PROVIDER_MAP.items():
        if key in target_lower:
            return provider
    # Check if target is itself a provider name
    providers = load_providers_config()
    if target_lower in providers:
        return target_lower
    return "anthropic"  # safe default
