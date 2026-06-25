"""output_contract.py — structured output validation & repair.

Validates a model's response against a JSON Schema (the ``output_contract`` of a
PromptSpec, or an explicit ``--schema``), and best-effort *repairs* malformed
output so it conforms — extracting JSON from surrounding prose, coercing scalar
types, and filling missing required fields.

Validation uses the optional ``jsonschema`` library when installed (full Draft
2020-12 support) and otherwise falls back to a built-in validator covering the
common subset: ``type``, ``required``, ``properties``, ``items``, ``enum``,
``additionalProperties``, ``minimum``/``maximum``, ``minLength``/``maxLength``,
``minItems``/``maxItems``, and ``pattern``. Base install stays dependency-free.

Public API
----------
  ``parse_payload(text, fmt="json")``       → (obj, error)
  ``validate_payload(obj, schema)``         → list[str]   (empty == valid)
  ``repair_payload(text, schema, fmt)``     → RepairResult
  ``load_schema(path)``                     → dict
  ``RepairResult``                          — repair outcome dataclass
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OutputContractError(ValueError):
    """Raised when a schema cannot be loaded or a payload cannot be parsed."""


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


def load_schema(path: str | Path) -> dict[str, Any]:
    """Load a JSON Schema from *path* (``.json`` or ``.yaml``)."""
    p = Path(path)
    if not p.exists():
        raise OutputContractError(f"Schema file not found: {p}")
    text = p.read_text(encoding="utf-8")
    try:
        raw = json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise OutputContractError(f"Failed to parse schema {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise OutputContractError(f"Schema {p} must be a mapping, got {type(raw).__name__}.")
    return raw


# ---------------------------------------------------------------------------
# Payload extraction / parsing
# ---------------------------------------------------------------------------

_FENCE_BLOCK_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)


def extract_code_block(text: str, lang: str | None = None) -> str | None:
    """Return the body of the first fenced code block (optionally matching *lang*)."""
    fallback: str | None = None
    for m in _FENCE_BLOCK_RE.finditer(text):
        block_lang = m.group(1).lower()
        body = m.group(2)
        if lang is not None and block_lang == lang:
            return body
        if fallback is None:
            fallback = body
    return fallback if lang is None else fallback


def _try_json(text: str) -> tuple[Any, str | None]:
    try:
        return json.loads(text), None
    except ValueError as exc:
        return None, str(exc)


def _extract_json_substring(text: str) -> str | None:
    """Find the first balanced ``{...}`` or ``[...]`` substring in *text*."""
    start = None
    opener = closer = ""
    for i, ch in enumerate(text):
        if ch in "{[":
            start, opener = i, ch
            closer = "}" if ch == "{" else "]"
            break
    if start is None:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : j + 1]
    return None


def parse_payload(text: str, fmt: str = "json") -> tuple[Any, str | None]:
    """Parse *text* into a Python object according to *fmt*.

    Returns ``(obj, error)`` — ``error`` is ``None`` on success. For ``json``,
    a direct parse is attempted first, then a fenced ```json``` block.
    ``markdown``/``text``/``code`` formats return the raw string unchanged.
    """
    fmt = (fmt or "json").lower()
    if fmt == "json":
        obj, err = _try_json(text)
        if err is not None:
            block = extract_code_block(text, "json") or extract_code_block(text)
            if block is not None:
                obj, err = _try_json(block)
        return obj, err
    if fmt == "yaml":
        try:
            return yaml.safe_load(text), None
        except yaml.YAMLError as exc:
            return None, str(exc)
    if fmt in ("markdown", "text", "code"):
        return text, None
    return None, f"unsupported output format {fmt!r}"


# ---------------------------------------------------------------------------
# Built-in validator (used when jsonschema is unavailable)
# ---------------------------------------------------------------------------

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _typename(v: Any) -> str:
    for name, check in _TYPE_CHECKS.items():
        if check(v):
            return name
    return type(v).__name__


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _builtin_validate(obj: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    loc = path or "<root>"
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPE_CHECKS.get(tt, lambda v: True)(obj) for tt in types):
            errors.append(f"{loc}: expected type {t}, got {_typename(obj)}")
            return  # type mismatch — deeper checks are meaningless

    if "enum" in schema and obj not in schema["enum"]:
        errors.append(f"{loc}: {obj!r} is not one of {schema['enum']}")

    if isinstance(obj, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in obj:
                errors.append(f"{_join(path, req)}: required property is missing")
        for k, sub in props.items():
            if k in obj and isinstance(sub, dict):
                _builtin_validate(obj[k], sub, _join(path, k), errors)
        if schema.get("additionalProperties") is False:
            for k in obj:
                if k not in props:
                    errors.append(f"{_join(path, k)}: additional property is not allowed")

    if isinstance(obj, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, el in enumerate(obj):
                _builtin_validate(el, items, f"{path}[{i}]", errors)
        if "minItems" in schema and len(obj) < schema["minItems"]:
            errors.append(f"{loc}: has {len(obj)} item(s), fewer than minItems={schema['minItems']}")
        if "maxItems" in schema and len(obj) > schema["maxItems"]:
            errors.append(f"{loc}: has {len(obj)} item(s), more than maxItems={schema['maxItems']}")

    if isinstance(obj, str):
        if "minLength" in schema and len(obj) < schema["minLength"]:
            errors.append(f"{loc}: length {len(obj)} < minLength={schema['minLength']}")
        if "maxLength" in schema and len(obj) > schema["maxLength"]:
            errors.append(f"{loc}: length {len(obj)} > maxLength={schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], obj) is None:
            errors.append(f"{loc}: does not match pattern {schema['pattern']!r}")

    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            errors.append(f"{loc}: {obj} < minimum={schema['minimum']}")
        if "maximum" in schema and obj > schema["maximum"]:
            errors.append(f"{loc}: {obj} > maximum={schema['maximum']}")


def validate_payload(obj: Any, schema: dict[str, Any]) -> list[str]:
    """Return a list of validation error strings (empty means *obj* is valid).

    Uses ``jsonschema`` when installed, otherwise the built-in subset validator.
    """
    try:
        import jsonschema  # type: ignore[import-not-found]
    except ImportError:
        jsonschema = None  # type: ignore[assignment]

    if jsonschema is not None:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema)
        out: list[str] = []
        for err in sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path)):
            loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
            out.append(f"{loc}: {err.message}")
        return out

    errors: list[str] = []
    _builtin_validate(obj, schema, "", errors)
    return errors


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


@dataclass
class RepairResult:
    """Outcome of :func:`repair_payload`."""

    repaired_text: str
    obj: Any
    repairs: list[str] = field(default_factory=list)
    valid: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.repairs)


_TYPE_ZERO: dict[str, Any] = {
    "object": {},
    "array": [],
    "string": "",
    "number": 0,
    "integer": 0,
    "boolean": False,
    "null": None,
}


def _default_for(schema: dict[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    t = schema.get("type")
    if isinstance(t, list):
        t = t[0] if t else None
    return _TYPE_ZERO.get(t) if isinstance(t, str) else None


def _coerce(obj: Any, schema: dict[str, Any], path: str, repairs: list[str]) -> Any:
    t = schema.get("type")
    types = t if isinstance(t, list) else ([t] if t else [])

    # Scalar coercions — only when the current value is the "wrong" scalar.
    if "string" in types and isinstance(obj, (int, float, bool)):
        repairs.append(f"{path or '<root>'}: coerced {_typename(obj)} to string")
        return "true" if obj is True else "false" if obj is False else str(obj)
    if "integer" in types and isinstance(obj, str) and re.fullmatch(r"-?\d+", obj.strip()):
        repairs.append(f"{path or '<root>'}: coerced string to integer")
        return int(obj.strip())
    if "number" in types and isinstance(obj, str):
        try:
            val = float(obj.strip())
        except ValueError:
            val = None
        if val is not None:
            repairs.append(f"{path or '<root>'}: coerced string to number")
            return val
    if "boolean" in types and isinstance(obj, str) and obj.strip().lower() in ("true", "false"):
        repairs.append(f"{path or '<root>'}: coerced string to boolean")
        return obj.strip().lower() == "true"

    if isinstance(obj, dict) and (schema.get("properties") or "object" in types):
        props = schema.get("properties", {})
        for k, sub in props.items():
            if k in obj and isinstance(sub, dict):
                obj[k] = _coerce(obj[k], sub, _join(path, k), repairs)
        for req in schema.get("required", []):
            if req not in obj:
                obj[req] = _default_for(props.get(req, {}))
                repairs.append(f"{_join(path, req)}: added missing required field")
        return obj

    if isinstance(obj, list) and isinstance(schema.get("items"), dict):
        return [_coerce(el, schema["items"], f"{path}[{i}]", repairs) for i, el in enumerate(obj)]

    return obj


def repair_payload(text: str, schema: dict[str, Any], fmt: str = "json") -> RepairResult:
    """Best-effort coerce *text* into a payload that satisfies *schema*.

    Steps: parse (or extract embedded JSON from prose) → coerce scalar types →
    fill missing required fields from ``default``/type → re-validate. The result
    carries the repaired text, the parsed object, a human-readable list of the
    repairs made, and the residual validation errors (if any).
    """
    repairs: list[str] = []
    obj, err = parse_payload(text, fmt)

    if (err is not None or obj is None) and fmt in ("json", "yaml"):
        substring = _extract_json_substring(text)
        if substring is not None:
            candidate, sub_err = _try_json(substring)
            if sub_err is None:
                obj, err = candidate, None
                repairs.append("extracted JSON payload from surrounding text")

    if err is not None or obj is None:
        return RepairResult(
            repaired_text=text,
            obj=None,
            repairs=repairs,
            valid=False,
            errors=[f"could not parse payload: {err or 'no JSON found'}"],
        )

    obj = _coerce(obj, schema, "", repairs)
    errors = validate_payload(obj, schema)
    repaired_text = json.dumps(obj, indent=2, ensure_ascii=False)
    return RepairResult(
        repaired_text=repaired_text,
        obj=obj,
        repairs=repairs,
        valid=not errors,
        errors=errors,
    )
