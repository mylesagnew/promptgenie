"""config.py — load and validate .promptgenie.yaml project config."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ScannerConfig:
    allowlist: list[str] = field(default_factory=list)
    disabled_rules: list[str] = field(default_factory=list)
    severity_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class LinterConfig:
    disabled_rules: list[str] = field(default_factory=list)
    custom_vague_verbs: list[str] = field(default_factory=list)


@dataclass
class PromptGenieConfig:
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    linter: LinterConfig = field(default_factory=LinterConfig)


_VALID_RISK_LEVELS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


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
        allowlist=[str(v) for v in raw.get("allowlist", [])],
        disabled_rules=[str(v) for v in raw.get("disabled_rules", [])],
        severity_overrides=overrides,
    )


def _parse_linter(raw: dict[str, Any]) -> LinterConfig:
    return LinterConfig(
        disabled_rules=[str(v) for v in raw.get("disabled_rules", [])],
        custom_vague_verbs=[str(v) for v in raw.get("custom_vague_verbs", [])],
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
