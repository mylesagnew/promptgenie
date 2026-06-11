"""spec.py — PromptSpec loader, validator, and dataclass definitions.

A PromptSpec is a declarative YAML (or JSON) file that describes a single
prompt execution unit: what prompt to use, which provider to send it to,
what context to assemble, which policies to enforce, and what output shape
to expect.

Minimal example::

    version: 1
    name: "code-review"
    target: claude-code
    template: agentic-task
    vars:
      component: auth
    context:
      - type: git_diff
    policy:
      - no-secrets
    output_contract:
      format: markdown

Public API
----------
``load_spec(path)``        → PromptSpec
``render_spec(spec, vars)`` → rendered prompt string with variables resolved
``validate_spec(spec)``    → list[str] of validation errors (empty = valid)
``SPEC_SCHEMA_PATH``       → Path to the JSON Schema file
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from promptgenie.core.errors import EXIT_USAGE, EXIT_TEMPLATE, PromptGenieError

SPEC_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "promptspec.schema.json"

_VALID_MODES = {"chat", "completion", "agentic"}
_VALID_CONTEXT_TYPES = {"file", "glob", "stdin", "env", "cmd", "git_diff", "git_staged", "url"}
_VALID_OUTPUT_FORMATS = {"text", "json", "yaml", "markdown", "code"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ContextSource:
    type: str  # file | glob | stdin | env | cmd | git_diff | git_staged | url
    path: str = ""
    pattern: str = ""
    var: str = ""
    command: str = ""
    url: str = ""
    label: str = ""
    max_bytes: int = 0  # 0 = no limit
    policy_gated: bool = True


@dataclass
class OutputContract:
    format: str = "text"  # text | json | yaml | markdown | code
    schema: dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 0
    min_tokens: int = 0


@dataclass
class RunOptions:
    dry_run: bool = False
    stream: bool = True
    timeout: int = 120
    retries: int = 0
    require_clean: bool = False
    no_history: bool = False


@dataclass
class PromptSpec:
    version: int
    name: str
    target: str
    template: str | None = None
    mode: str = "chat"
    vars: dict[str, Any] = field(default_factory=dict)
    context: list[ContextSource] = field(default_factory=list)
    policy: list[str] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    prompt: str | None = None
    output_contract: OutputContract = field(default_factory=OutputContract)
    run: RunOptions = field(default_factory=RunOptions)
    # Original file path for relative path resolution
    _source_path: Path | None = field(default=None, repr=False, compare=False)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_spec(path: str | Path) -> PromptSpec:
    """Load a PromptSpec from *path* (YAML or JSON).

    Raises
    ------
    PromptGenieError(EXIT_USAGE)
        If the file cannot be parsed or the structure is invalid.
    """
    p = Path(path)
    if not p.exists():
        raise PromptGenieError(f"Spec file not found: {p}", code=EXIT_USAGE)

    raw_text = p.read_text(encoding="utf-8")
    try:
        if p.suffix.lower() == ".json":
            raw: Any = json.loads(raw_text)
        else:
            raw = yaml.safe_load(raw_text)
    except Exception as exc:
        raise PromptGenieError(
            f"Failed to parse spec file {p}: {exc}",
            code=EXIT_USAGE,
            hint="Check that the file is valid YAML or JSON.",
        ) from exc

    if not isinstance(raw, dict):
        raise PromptGenieError(
            f"Spec file {p} must be a YAML/JSON mapping, got {type(raw).__name__}.",
            code=EXIT_USAGE,
        )

    errors = _validate_raw(raw)
    if errors:
        joined = "\n  ".join(errors)
        raise PromptGenieError(
            f"Spec file {p} is invalid:\n  {joined}",
            code=EXIT_USAGE,
        )

    spec = _build_spec(raw)
    spec._source_path = p
    return spec


def _validate_raw(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if raw.get("version") != 1:
        errors.append("'version' must be 1")
    if not raw.get("name"):
        errors.append("'name' is required and must be non-empty")
    if not raw.get("target"):
        errors.append("'target' is required and must be non-empty")
    mode = raw.get("mode", "chat")
    if mode not in _VALID_MODES:
        errors.append(f"'mode' must be one of {sorted(_VALID_MODES)}, got {mode!r}")
    for i, src in enumerate(raw.get("context", [])):
        if not isinstance(src, dict):
            errors.append(f"context[{i}] must be a mapping")
            continue
        t = src.get("type", "")
        if t not in _VALID_CONTEXT_TYPES:
            errors.append(
                f"context[{i}].type must be one of {sorted(_VALID_CONTEXT_TYPES)}, got {t!r}"
            )
    oc = raw.get("output_contract", {})
    if isinstance(oc, dict):
        fmt = oc.get("format", "text")
        if fmt not in _VALID_OUTPUT_FORMATS:
            errors.append(
                f"output_contract.format must be one of {sorted(_VALID_OUTPUT_FORMATS)}, got {fmt!r}"
            )
    return errors


def _build_spec(raw: dict[str, Any]) -> PromptSpec:
    context_sources = [_build_context_source(s) for s in raw.get("context", [])]
    oc_raw = raw.get("output_contract") or {}
    oc = OutputContract(
        format=oc_raw.get("format", "text"),
        schema=oc_raw.get("schema") or {},
        max_tokens=int(oc_raw.get("max_tokens", 0)),
        min_tokens=int(oc_raw.get("min_tokens", 0)),
    )
    run_raw = raw.get("run") or {}
    run_opts = RunOptions(
        dry_run=bool(run_raw.get("dry_run", False)),
        stream=bool(run_raw.get("stream", True)),
        timeout=int(run_raw.get("timeout", 120)),
        retries=int(run_raw.get("retries", 0)),
        require_clean=bool(run_raw.get("require_clean", False)),
        no_history=bool(run_raw.get("no_history", False)),
    )
    return PromptSpec(
        version=int(raw["version"]),
        name=str(raw["name"]),
        target=str(raw["target"]),
        template=raw.get("template"),
        mode=str(raw.get("mode", "chat")),
        vars=dict(raw.get("vars") or {}),
        context=context_sources,
        policy=list(raw.get("policy") or []),
        provider=raw.get("provider"),
        model=raw.get("model"),
        system_prompt=raw.get("system_prompt"),
        prompt=raw.get("prompt"),
        output_contract=oc,
        run=run_opts,
    )


def _build_context_source(raw: dict[str, Any]) -> ContextSource:
    return ContextSource(
        type=str(raw.get("type", "")),
        path=str(raw.get("path", "")),
        pattern=str(raw.get("pattern", "")),
        var=str(raw.get("var", "")),
        command=str(raw.get("command", "")),
        url=str(raw.get("url", "")),
        label=str(raw.get("label", "")),
        max_bytes=int(raw.get("max_bytes", 0)),
        policy_gated=bool(raw.get("policy_gated", True)),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_spec(spec: PromptSpec) -> list[str]:
    """Return a list of validation error strings. Empty = valid."""
    raw = _spec_to_dict(spec)
    return _validate_raw(raw)


# ---------------------------------------------------------------------------
# Render (resolve variables in prompt text)
# ---------------------------------------------------------------------------


def render_spec(spec: PromptSpec, resolved_vars: dict[str, Any]) -> str:
    """Return the prompt text from *spec* with *resolved_vars* substituted.

    Uses the ``prompt`` field directly, or falls back to the template name
    as placeholder text when no inline prompt is present.
    """
    text = spec.prompt or (f"[template:{spec.template}]" if spec.template else "")
    if not text:
        text = ""
    # Simple {{name}} substitution
    def _sub(m: re.Match) -> str:  # type: ignore[type-arg]
        name = m.group(1)
        if name in resolved_vars:
            return str(resolved_vars[name])
        return m.group(0)

    return re.sub(r"\{\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}\}", _sub, text)


# ---------------------------------------------------------------------------
# Serialise back to dict (for JSON/YAML output)
# ---------------------------------------------------------------------------


def _spec_to_dict(spec: PromptSpec) -> dict[str, Any]:
    return {
        "version": spec.version,
        "name": spec.name,
        "target": spec.target,
        "template": spec.template,
        "mode": spec.mode,
        "vars": spec.vars,
        "context": [
            {k: v for k, v in {
                "type": s.type,
                "path": s.path or None,
                "pattern": s.pattern or None,
                "var": s.var or None,
                "command": s.command or None,
                "url": s.url or None,
                "label": s.label or None,
                "max_bytes": s.max_bytes or None,
                "policy_gated": s.policy_gated,
            }.items() if v is not None}
            for s in spec.context
        ],
        "policy": spec.policy,
        "provider": spec.provider,
        "model": spec.model,
        "system_prompt": spec.system_prompt,
        "prompt": spec.prompt,
        "output_contract": {
            "format": spec.output_contract.format,
            **({"schema": spec.output_contract.schema} if spec.output_contract.schema else {}),
            **({"max_tokens": spec.output_contract.max_tokens} if spec.output_contract.max_tokens else {}),
            **({"min_tokens": spec.output_contract.min_tokens} if spec.output_contract.min_tokens else {}),
        },
        "run": {
            "dry_run": spec.run.dry_run,
            "stream": spec.run.stream,
            "timeout": spec.run.timeout,
            "retries": spec.run.retries,
            "require_clean": spec.run.require_clean,
            "no_history": spec.run.no_history,
        },
    }


# ---------------------------------------------------------------------------
# Init template
# ---------------------------------------------------------------------------

_INIT_TEMPLATE = """\
version: 1
name: "{name}"
target: {target}
# template: agentic-task        # optional: use a named template
mode: chat                      # chat | completion | agentic

# Inline prompt (or use template: above)
prompt: |
  Your prompt here. Use {{{{variable}}}} placeholders for dynamic values.

# Inline variable defaults (can be overridden with --var / --vars)
vars:
  # my_var: default_value

# Context sources assembled before sending to provider
# context:
#   - type: git_diff
#   - type: file
#     path: README.md
#   - type: glob
#     pattern: "src/**/*.py"
#     max_bytes: 32768

# Policy gate — names or paths of policy files
# policy:
#   - no-secrets

# Provider and model overrides (optional — uses target defaults)
# provider: ollama
# model: llama3

# Output contract — describe the expected response shape
output_contract:
  format: text          # text | json | yaml | markdown | code
  # max_tokens: 2048

# Runtime options
run:
  stream: true
  timeout: 120
  # dry_run: false
  # require_clean: false
"""


def spec_init_template(name: str, target: str = "claude-code") -> str:
    """Return a populated YAML starter PromptSpec string."""
    return _INIT_TEMPLATE.format(name=name, target=target)
