"""config.py — load and validate .promptgenie.yaml project config."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from promptgenie.core.linter import LintRule
    from promptgenie.core.scanner import ScanRule


@dataclass
class AllowlistEntry:
    """A single allowlist entry.

    *phrase*: text that, when found in a finding's matched region, suppresses it.
    *rules*:  if non-empty, suppression only applies to findings with these codes.
              If empty, the phrase suppresses any finding whose matched text contains it.

    YAML formats accepted:

        # Simple string — suppresses any finding whose matched text contains this phrase
        - "example-token-for-docs"

        # Scoped — suppresses only specified rule codes
        - phrase: "known-safe-deploy"
          rules:
            - PERM_005
    """

    phrase: str
    rules: list[str] = field(default_factory=list)  # empty = applies to all rules

    def suppresses(self, finding_code: str, matched_text: str) -> bool:
        """Return True if this entry suppresses the given finding."""
        if self.rules and finding_code not in self.rules:
            return False
        return self.phrase.lower() in matched_text.lower()


@dataclass
class ScannerConfig:
    allowlist: list[AllowlistEntry] = field(default_factory=list)
    disabled_rules: list[str] = field(default_factory=list)
    severity_overrides: dict[str, str] = field(default_factory=dict)
    custom_scan_rules: list[ScanRule] = field(default_factory=list)


@dataclass
class LinterConfig:
    disabled_rules: list[str] = field(default_factory=list)
    custom_vague_verbs: list[str] = field(default_factory=list)
    custom_lint_rules: list[LintRule] = field(default_factory=list)


@dataclass
class PromptGenieConfig:
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    linter: LinterConfig = field(default_factory=LinterConfig)


_VALID_RISK_LEVELS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def _parse_allowlist(raw_entries: list[Any]) -> list[AllowlistEntry]:
    entries: list[AllowlistEntry] = []
    for item in raw_entries:
        if isinstance(item, str):
            entries.append(AllowlistEntry(phrase=item))
        elif isinstance(item, dict):
            phrase = str(item.get("phrase", ""))
            if not phrase:
                raise ValueError(f"Allowlist entry {item!r} is missing a 'phrase' key.")
            rules = [str(r) for r in item.get("rules", [])]
            entries.append(AllowlistEntry(phrase=phrase, rules=rules))
        else:
            raise ValueError(
                f"Allowlist entry must be a string or a mapping, got {type(item).__name__}: {item!r}"
            )
    return entries


_VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
_VALID_SEVERITY = {"HIGH", "MEDIUM", "LOW", "INFO"}


def _parse_custom_scan_rules(raw_rules: list[Any]) -> list[ScanRule]:
    from promptgenie.core.scanner import ScanRule

    rules = []
    for entry in raw_rules:
        if not isinstance(entry, dict):
            raise ValueError(f"Custom scan rule must be a mapping, got {type(entry).__name__}.")
        rule_id = str(entry.get("id", ""))
        pattern = str(entry.get("pattern", ""))
        risk = str(entry.get("risk", "MEDIUM")).upper()
        confidence = str(entry.get("confidence", "MEDIUM")).upper()
        if not rule_id:
            raise ValueError(f"Custom scan rule missing 'id': {entry!r}")
        if not pattern:
            raise ValueError(f"Custom scan rule {rule_id!r} missing 'pattern'.")
        if risk not in _VALID_RISK_LEVELS:
            raise ValueError(f"Custom scan rule {rule_id!r}: invalid risk {risk!r}. Must be one of {sorted(_VALID_RISK_LEVELS)}.")
        if confidence not in _VALID_CONFIDENCE:
            raise ValueError(f"Custom scan rule {rule_id!r}: invalid confidence {confidence!r}. Must be one of {sorted(_VALID_CONFIDENCE)}.")
        rules.append(
            ScanRule(
                id=rule_id,
                category=str(entry.get("category", "custom")),
                pattern=pattern,
                risk=risk,  # type: ignore[arg-type]
                confidence=confidence,  # type: ignore[arg-type]
                message=str(entry.get("message", "")),
                recommendation=str(entry.get("recommendation", "")),
                false_positive_note=str(entry.get("false_positive_note", "")),
                use_original_text=bool(entry.get("use_original_text", False)),
            )
        )
    return rules


def _parse_custom_lint_rules(raw_rules: list[Any]) -> list[LintRule]:
    from promptgenie.core.linter import LintRule

    rules = []
    for entry in raw_rules:
        if not isinstance(entry, dict):
            raise ValueError(f"Custom lint rule must be a mapping, got {type(entry).__name__}.")
        rule_id = str(entry.get("id", ""))
        pattern = str(entry.get("pattern", ""))
        severity = str(entry.get("severity", "MEDIUM")).upper()
        confidence = str(entry.get("confidence", "MEDIUM")).upper()
        if not rule_id:
            raise ValueError(f"Custom lint rule missing 'id': {entry!r}")
        if not pattern:
            raise ValueError(f"Custom lint rule {rule_id!r} missing 'pattern'.")
        if severity not in _VALID_SEVERITY:
            raise ValueError(f"Custom lint rule {rule_id!r}: invalid severity {severity!r}. Must be one of {sorted(_VALID_SEVERITY)}.")
        if confidence not in _VALID_CONFIDENCE:
            raise ValueError(f"Custom lint rule {rule_id!r}: invalid confidence {confidence!r}. Must be one of {sorted(_VALID_CONFIDENCE)}.")
        rules.append(
            LintRule(
                id=rule_id,
                category=str(entry.get("category", "custom")),
                pattern=pattern,
                severity=severity,  # type: ignore[arg-type]
                confidence=confidence,  # type: ignore[arg-type]
                message=str(entry.get("message", "")),
                suggestion=str(entry.get("suggestion", "")),
                false_positive_note=str(entry.get("false_positive_note", "")),
                negate=bool(entry.get("negate", False)),
                requires_agentic=bool(entry.get("requires_agentic", False)),
            )
        )
    return rules


def _parse_scanner(raw: dict[str, Any]) -> ScannerConfig:
    overrides: dict[str, str] = {}
    for code, level in raw.get("severity_overrides", {}).items():
        level_upper = str(level).upper()
        if level_upper not in _VALID_RISK_LEVELS:
            raise ValueError(
                f"Invalid severity override for {code!r}: {level!r}. "
                f"Must be one of {sorted(_VALID_RISK_LEVELS)}."
            )
        overrides[str(code)] = level_upper

    return ScannerConfig(
        allowlist=_parse_allowlist(raw.get("allowlist", [])),
        disabled_rules=[str(v) for v in raw.get("disabled_rules", [])],
        severity_overrides=overrides,
        custom_scan_rules=_parse_custom_scan_rules(raw.get("custom_rules", [])),
    )


def _parse_linter(raw: dict[str, Any]) -> LinterConfig:
    return LinterConfig(
        disabled_rules=[str(v) for v in raw.get("disabled_rules", [])],
        custom_vague_verbs=[str(v) for v in raw.get("custom_vague_verbs", [])],
        custom_lint_rules=_parse_custom_lint_rules(raw.get("custom_rules", [])),
    )


def load_config(path: str | Path | None = None) -> PromptGenieConfig:
    """Load config from *path*, or search for .promptgenie.yaml in cwd and parents."""
    if path is not None:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
    else:
        found = _find_config()
        if found is None:
            return PromptGenieConfig()
        config_path = found

    with config_path.open() as fh:
        raw = yaml.safe_load(fh) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Config file {config_path} must be a YAML mapping.")

    return PromptGenieConfig(
        scanner=_parse_scanner(raw.get("scanner", {})),
        linter=_parse_linter(raw.get("linter", {})),
    )


def _find_config() -> Path | None:
    """Walk from cwd upward looking for .promptgenie.yaml."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / ".promptgenie.yaml"
        if candidate.exists():
            return candidate
    return None
