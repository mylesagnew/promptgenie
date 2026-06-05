"""
models.py — typed dataclass models for PromptGenie configs and results.

Using dataclasses keeps the runtime dependency footprint minimal while giving
editors, mypy, and tests a concrete schema to verify against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ── Config / schema models ───────────────────────────────────────────────────


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

    @classmethod
    def from_dict(cls, data: dict, profile_id: str = "") -> Profile:
        return cls(
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

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("Profile 'name' is required.")
        return errors


@dataclass
class Template:
    """A prompt template (e.g. agentic-task, threat-model)."""

    id: str
    name: str
    description: str = ""
    sections: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> Template:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "")),
            description=data.get("description", ""),
            sections=data.get("sections", []),
            tags=data.get("tags", []),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id:
            errors.append("Template 'id' is required.")
        if not self.name:
            errors.append("Template 'name' is required.")
        return errors


@dataclass
class ContextPackMeta:
    """Lightweight metadata for a context pack (used in list views)."""

    id: str
    name: str
    description: str = ""
    stack: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict, pack_id: str = "") -> ContextPackMeta:
        return cls(
            id=pack_id,
            name=data.get("name", pack_id),
            description=data.get("description", ""),
            stack=data.get("stack", []),
        )


# ── Result models ────────────────────────────────────────────────────────────


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
