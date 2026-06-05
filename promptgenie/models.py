"""
models.py — typed dataclass models for PromptGenie configs and results.

Using dataclasses keeps the runtime dependency footprint minimal while giving
editors, mypy, and tests a concrete schema to verify against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Schema constants ──────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_KNOWN_PROFILE_CATEGORIES = {
    "agentic-coding",
    "general-assistant",
    "ide-coding",
    "security",
    "multimodal",
    "research",
}

_KNOWN_PROFILE_KEYS = {
    "name",
    "category",
    "strengths",
    "risks",
    "required_sections",
    "forbidden_patterns",
    "stop_conditions",
    "security_controls",
    "scope_guidance",
    "default_output_format",
}

_KNOWN_TEMPLATE_KEYS = {"id", "name", "description", "sections", "category", "tags"}

_KNOWN_CONTEXT_PACK_KEYS = {
    "name",
    "description",
    "stack",
    "architecture",
    "coding_style",
    "forbidden_changes",
    "known_pitfalls",
    "terminology",
    "output_format",
    "preferred_output_format",
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _check_string_list(value: Any, field_name: str) -> list[str]:
    """Return error strings if *value* is not a list of non-empty strings."""
    errors: list[str] = []
    if not isinstance(value, list):
        errors.append(f"'{field_name}' must be a list, got {type(value).__name__}.")
        return errors
    for i, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"'{field_name}[{i}]' must be a string, got {type(item).__name__}.")
        elif not item.strip():
            errors.append(f"'{field_name}[{i}]' must not be blank.")
    return errors


def _unknown_key_warnings(data: dict, known: set[str], kind: str) -> list[str]:
    unknown = sorted(set(data.keys()) - known)
    if unknown:
        return [f"Unknown {kind} key(s): {', '.join(unknown)}. May be a typo."]
    return []


# ── Config / schema models ────────────────────────────────────────────────────


@dataclass
class Profile:
    """A target model profile (e.g. claude-code, chatgpt)."""

    id: str
    name: str
    category: str = ""
    required_sections: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    security_controls: list[str] = field(default_factory=list)
    scope_guidance: str = ""
    default_output_format: str = "Structured markdown."

    # Raw dict preserved for unknown-key detection
    _raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict, profile_id: str = "") -> Profile:
        obj = cls(
            id=profile_id or data.get("id", ""),
            name=data.get("name", profile_id),
            category=data.get("category", ""),
            required_sections=data.get("required_sections", []),
            forbidden_patterns=data.get("forbidden_patterns", []),
            stop_conditions=data.get("stop_conditions", []),
            security_controls=data.get("security_controls", []),
            scope_guidance=data.get("scope_guidance", ""),
            default_output_format=data.get("default_output_format", "Structured markdown."),
        )
        obj._raw = data
        return obj

    def validate(self) -> tuple[list[str], list[str]]:
        """Return (errors, warnings). Errors are blocking; warnings are advisory."""
        errors: list[str] = []
        warnings: list[str] = []

        # Required: name
        if not self.name or not str(self.name).strip():
            errors.append("'name' is required and must not be blank.")

        # Required: category
        if not self.category or not str(self.category).strip():
            errors.append("'category' is required and must not be blank.")
        elif self.category not in _KNOWN_PROFILE_CATEGORIES:
            warnings.append(
                f"'category' value {self.category!r} is not a recognised category. "
                f"Known: {', '.join(sorted(_KNOWN_PROFILE_CATEGORIES))}."
            )

        # Type checks on list fields
        for fname, fval in [
            ("required_sections", self.required_sections),
            ("forbidden_patterns", self.forbidden_patterns),
            ("stop_conditions", self.stop_conditions),
            ("security_controls", self.security_controls),
        ]:
            errors.extend(_check_string_list(fval, fname))

        # Type checks on string fields (cast to Any so mypy allows isinstance check)
        str_fields: list[tuple[str, Any]] = [
            ("scope_guidance", self.scope_guidance),
            ("default_output_format", self.default_output_format),
        ]
        for fname, fval in str_fields:
            if not isinstance(fval, str):
                errors.append(f"'{fname}' must be a string, got {type(fval).__name__}.")

        # Warnings for missing recommended fields
        if not self.required_sections:
            warnings.append(
                "'required_sections' is empty — the generator cannot enforce section completeness."
            )
        if not self.stop_conditions:
            warnings.append(
                "'stop_conditions' is empty — agentic prompts using this profile will lack guardrails."
            )
        if not self.scope_guidance:
            warnings.append("'scope_guidance' is empty — consider adding scope instructions.")

        # Unknown key detection
        warnings.extend(_unknown_key_warnings(self._raw, _KNOWN_PROFILE_KEYS, "profile"))

        return errors, warnings


@dataclass
class Template:
    """A prompt template (e.g. agentic-task, threat-model)."""

    id: str
    name: str
    description: str = ""
    sections: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    _raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict) -> Template:
        obj = cls(
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "")),
            description=data.get("description", ""),
            sections=data.get("sections", []),
            tags=data.get("tags", []),
        )
        obj._raw = data
        return obj

    def validate(self) -> tuple[list[str], list[str]]:
        """Return (errors, warnings)."""
        errors: list[str] = []
        warnings: list[str] = []

        # Required: id
        if not self.id or not str(self.id).strip():
            errors.append("'id' is required and must not be blank.")
        elif not _SLUG_RE.match(self.id):
            errors.append(
                f"'id' must be lowercase letters, digits, and hyphens only (got {self.id!r})."
            )

        # Required: name
        if not self.name or not str(self.name).strip():
            errors.append("'name' is required and must not be blank.")

        # Required: sections (non-empty)
        if not isinstance(self.sections, list):
            errors.append(f"'sections' must be a list, got {type(self.sections).__name__}.")
        elif not self.sections:
            errors.append("'sections' must not be empty — a template needs at least one section.")
        else:
            errors.extend(_check_string_list(self.sections, "sections"))

        # Type checks
        if not isinstance(self.tags, list):
            errors.append(f"'tags' must be a list, got {type(self.tags).__name__}.")

        # Warnings
        if not self.description:
            warnings.append("'description' is missing — consider adding a short summary.")

        # Unknown key detection
        warnings.extend(_unknown_key_warnings(self._raw, _KNOWN_TEMPLATE_KEYS, "template"))

        return errors, warnings


@dataclass
class ContextPackMeta:
    """Lightweight metadata for a context pack (used in list views)."""

    id: str
    name: str
    description: str = ""
    stack: list[str] = field(default_factory=list)

    _raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict, pack_id: str = "") -> ContextPackMeta:
        obj = cls(
            id=pack_id,
            name=data.get("name", pack_id),
            description=data.get("description", ""),
            stack=data.get("stack", []),
        )
        obj._raw = data
        return obj

    def validate(self) -> tuple[list[str], list[str]]:
        """Return (errors, warnings)."""
        errors: list[str] = []
        warnings: list[str] = []

        # Required: name
        if not self.name or not str(self.name).strip():
            errors.append("'name' is required and must not be blank.")

        # Type check: stack
        if self.stack and not isinstance(self.stack, list):
            errors.append(f"'stack' must be a list, got {type(self.stack).__name__}.")
        elif isinstance(self.stack, list):
            errors.extend(_check_string_list(self.stack, "stack"))

        # Warnings for commonly expected fields
        if not self.description:
            warnings.append("'description' is missing — consider adding a one-line summary.")
        if not self.stack:
            warnings.append("'stack' is empty — consider listing the tech stack.")

        # Unknown key detection
        warnings.extend(_unknown_key_warnings(self._raw, _KNOWN_CONTEXT_PACK_KEYS, "context-pack"))

        return errors, warnings


# ── Result models ─────────────────────────────────────────────────────────────


@dataclass
class GenerateResult:
    """Output of a single generate_prompt() call."""

    prompt: str
    target: str
    template: str
    token_estimate: int
    score: dict  # {"total": int, "breakdown": dict[str, int]}
    lint_issues: list = field(default_factory=list)  # list[LintIssue]
    scan_findings: list = field(default_factory=list)  # list[SecurityFinding]
    context_pack_id: str = ""

    @property
    def score_total(self) -> int:
        return int(self.score.get("total", 0))

    @property
    def has_high_lint(self) -> bool:
        return any(getattr(i, "severity", "") == "HIGH" for i in self.lint_issues)

    @property
    def has_critical_security(self) -> bool:
        return any(getattr(f, "risk", "") in ("CRITICAL", "HIGH") for f in self.scan_findings)


@dataclass
class ValidationResult:
    """Result of validating a YAML config file."""

    path: Path
    kind: str  # "profile" | "template" | "context-pack" | "workflow" | "prompt-test"
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "✓" if self.valid else "✗"
        lines = [f"{status} [{self.kind}] {self.path}"]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        return "\n".join(lines)
