"""variables.py — interactive variable resolver for PromptGenie.

Detects ``{{variable}}`` (and ``{{variable:type:default}}``) placeholders in
prompt text and resolves them from multiple sources in priority order:

  1. ``--var key=value`` flags (CLI overrides — highest priority)
  2. ``--vars file.yaml`` values file
  3. Environment variables (``PG_<UPPER_NAME>`` by default)
  4. Interactive prompt (unless ``--no-input`` is set)
  5. Inline default from the placeholder itself ``{{name:string:fallback}}``

If a variable remains unresolved after all sources are exhausted:
  - ``--no-input`` mode raises ``PromptGenieError(code=EXIT_USAGE)``
  - Interactive mode prompts the user via ``click.prompt``

Placeholder syntax
------------------
  ``{{name}}``                    — required, type string, no default
  ``{{name:string:default}}``     — optional with inline default
  ``{{name:secret}}``             — secret: masked in logs, prompted with hide_input
  ``{{name:int:42}}``             — integer type coercion

Schema YAML (``--vars-schema schema.yaml``)
-------------------------------------------
::

    variables:
      api_env:
        type: string
        required: true
        description: "Target environment (prod/staging/dev)"
        allowed_values: [prod, staging, dev]
      debug:
        type: bool
        default: false
        required: false
      token:
        type: secret
        required: true

Public API
----------
``find_variables(text)``           → list of placeholder names in order
``resolve_variables(text, ...)``   → (rendered_text, resolved_dict)
``parse_cli_vars(var_list)``       → dict from ``["key=val", ...]``
``load_vars_file(path)``           → dict from a YAML/JSON vars file
``VarResolutionError``             → raised on unresolved required var
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from promptgenie.core.errors import EXIT_USAGE, PromptGenieError

# ---------------------------------------------------------------------------
# Regex — matches {{name}}, {{name:type}}, {{name:type:default}}
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(
    r"\{\{([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?)?\}\}"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VariableSpec:
    """Schema for a single template variable."""

    name: str
    type: str = "string"  # string | int | float | bool | secret
    default: str | None = None
    required: bool = True
    secret: bool = False
    description: str = ""
    allowed_values: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.type == "secret":
            self.secret = True


@dataclass
class PlaceholderMatch:
    """A single placeholder found in the source text."""

    name: str
    raw: str  # the full ``{{...}}`` string as it appeared
    inline_type: str = "string"
    inline_default: str | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VarResolutionError(PromptGenieError):
    """Raised when a required variable cannot be resolved and --no-input is set."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Required variable '{name}' is unresolved and --no-input was set.",
            code=EXIT_USAGE,
            hint="Supply a value with --var {name}=<value> or via a --vars file.".format(
                name=name
            ),
        )
        self.var_name = name


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def find_variables(text: str) -> list[str]:
    """Return an ordered, deduplicated list of placeholder names in *text*."""
    seen: dict[str, None] = {}
    for m in _PLACEHOLDER_RE.finditer(text):
        seen[m.group(1)] = None
    return list(seen)


def _parse_placeholders(text: str) -> list[PlaceholderMatch]:
    """Return every placeholder match (including duplicates) for substitution."""
    matches = []
    for m in _PLACEHOLDER_RE.finditer(text):
        matches.append(
            PlaceholderMatch(
                name=m.group(1),
                raw=m.group(0),
                inline_type=m.group(2) or "string",
                inline_default=m.group(3),
            )
        )
    return matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_cli_vars(var_list: tuple[str, ...] | list[str]) -> dict[str, str]:
    """Parse ``["key=val", ...]`` into ``{"key": "val"}``."""
    result: dict[str, str] = {}
    for item in var_list:
        if "=" not in item:
            raise PromptGenieError(
                f"Invalid --var format: '{item}' — expected key=value.",
                code=EXIT_USAGE,
            )
        k, _, v = item.partition("=")
        result[k.strip()] = v
    return result


def load_vars_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML or JSON vars file, returning a flat key→value dict."""
    p = Path(path)
    if not p.exists():
        raise PromptGenieError(f"Vars file not found: {p}", code=EXIT_USAGE)
    text = p.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise PromptGenieError(f"Could not parse vars file {p}: {e}", code=EXIT_USAGE) from e
    if not isinstance(data, dict):
        raise PromptGenieError(
            f"Vars file {p} must be a YAML mapping (got {type(data).__name__}).",
            code=EXIT_USAGE,
        )
    return {str(k): v for k, v in data.items()}


def load_schema_file(path: str | Path) -> dict[str, VariableSpec]:
    """Load a vars-schema YAML file and return a name→VariableSpec mapping."""
    p = Path(path)
    if not p.exists():
        raise PromptGenieError(f"Schema file not found: {p}", code=EXIT_USAGE)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    variables_raw = raw.get("variables", {})
    specs: dict[str, VariableSpec] = {}
    for name, attrs in variables_raw.items():
        if not isinstance(attrs, dict):
            attrs = {}
        specs[name] = VariableSpec(
            name=name,
            type=str(attrs.get("type", "string")),
            default=attrs.get("default"),
            required=bool(attrs.get("required", True)),
            secret=bool(attrs.get("secret", False)) or attrs.get("type") == "secret",
            description=str(attrs.get("description", "")),
            allowed_values=[str(v) for v in attrs.get("allowed_values", [])],
        )
    return specs


def _coerce(value: str, var_type: str) -> str:
    """Validate *value* against *var_type* and return it as a string.

    Currently just validates; coercion for non-string types raises early if the
    value is obviously wrong, but always returns a string for substitution.
    """
    if var_type in ("int",):
        try:
            int(value)
        except ValueError as e:
            raise PromptGenieError(
                f"Variable value '{value}' is not a valid integer.", code=EXIT_USAGE
            ) from e
    elif var_type in ("float",):
        try:
            float(value)
        except ValueError as e:
            raise PromptGenieError(
                f"Variable value '{value}' is not a valid float.", code=EXIT_USAGE
            ) from e
    elif var_type in ("bool",):
        if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
            raise PromptGenieError(
                f"Variable value '{value}' is not a valid boolean (true/false).", code=EXIT_USAGE
            )
    return value


# ---------------------------------------------------------------------------
# Core resolver
# ---------------------------------------------------------------------------


def resolve_variables(
    text: str,
    cli_vars: dict[str, str] | None = None,
    vars_file_values: dict[str, Any] | None = None,
    schema: dict[str, VariableSpec] | None = None,
    env_prefix: str = "PG_",
    no_input: bool = False,
) -> tuple[str, dict[str, str]]:
    """Resolve all ``{{variable}}`` placeholders in *text*.

    Parameters
    ----------
    text:
        The source text containing ``{{placeholder}}`` markers.
    cli_vars:
        Values from ``--var key=value`` flags (highest priority).
    vars_file_values:
        Values from ``--vars file.yaml``.
    schema:
        Optional schema from ``--vars-schema`` giving types, defaults, etc.
    env_prefix:
        Prefix for env-var lookups (default ``PG_``). A variable named
        ``api_key`` is looked up as ``PG_API_KEY``.
    no_input:
        If True, never prompt interactively — raise ``VarResolutionError``
        for any unresolved required variable instead.

    Returns
    -------
    rendered_text:
        The text with all placeholders replaced.
    resolved:
        Mapping of variable name → resolved value (secrets shown as ``***``).
    """
    import click

    cli_vars = cli_vars or {}
    vars_file_values = vars_file_values or {}
    schema = schema or {}

    placeholders = _parse_placeholders(text)
    if not placeholders:
        return text, {}

    resolved: dict[str, str] = {}

    # Resolve each unique variable name once
    for ph in placeholders:
        name = ph.name
        if name in resolved:
            continue

        spec = schema.get(name)
        var_type = spec.type if spec else ph.inline_type
        is_secret = (spec.secret if spec else False) or var_type == "secret"
        is_required = spec.required if spec else (ph.inline_default is None)
        default = (spec.default if spec else None) or ph.inline_default
        description = spec.description if spec else ""
        allowed = spec.allowed_values if spec else []

        # Resolution order
        value: str | None = None

        # 1. --var CLI override
        if name in cli_vars:
            value = str(cli_vars[name])

        # 2. --vars file
        elif name in vars_file_values:
            value = str(vars_file_values[name])

        # 3. Environment variable
        else:
            env_key = env_prefix + name.upper()
            env_val = os.environ.get(env_key)
            if env_val is not None:
                value = env_val

        # 4. Interactive prompt / default
        if value is None:
            if no_input:
                if default is not None:
                    value = str(default)
                elif not is_required:
                    value = ""
                else:
                    raise VarResolutionError(name)
            else:
                # Interactive
                prompt_text = f"Enter value for {name!r}"
                if description:
                    prompt_text += f" ({description})"
                if default is not None:
                    value = click.prompt(
                        prompt_text,
                        default=str(default),
                        hide_input=is_secret,
                    )
                elif not is_required:
                    value = click.prompt(
                        prompt_text,
                        default="",
                        hide_input=is_secret,
                    )
                else:
                    value = click.prompt(prompt_text, hide_input=is_secret)

        # Validate allowed values
        if allowed and value not in allowed:
            raise PromptGenieError(
                f"Variable '{name}' value '{value}' is not in allowed values: {allowed}.",
                code=EXIT_USAGE,
            )

        # Type coercion / validation
        value = _coerce(str(value), var_type)

        resolved[name] = value

    # Substitute all placeholders (same name may appear multiple times)
    rendered = text
    for ph in placeholders:
        rendered = rendered.replace(ph.raw, resolved[ph.name], 1)

    # Build display dict (mask secrets)
    display_resolved = {
        k: "***" if (schema.get(k) and schema[k].secret) else v for k, v in resolved.items()
    }

    return rendered, display_resolved
