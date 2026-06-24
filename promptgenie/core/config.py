"""config.py — load and validate .promptgenie.yaml project config."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from promptgenie.core.fileio import safe_read_yaml

if TYPE_CHECKING:
    from promptgenie.core.linter import LintRule
    from promptgenie.core.scanner import ScanRule


@dataclass
class AllowlistEntry:
    """A single allowlist entry.

    *phrase*:  text that, when found in a finding's matched region, suppresses it.
    *rules*:   if non-empty, suppression only applies to findings with these codes.
               If empty, the phrase suppresses any finding whose matched text contains it.
    *expires*: ISO date string "YYYY-MM-DD". Suppression is inactive after this date.
               Leave empty (default) for a permanent suppression.
    *reason*:  Free-text documentation — ticket reference, explanation, etc.

    YAML formats accepted::

        # Simple string — permanent, applies to any finding whose matched text contains phrase
        - "example-token-for-docs"

        # Scoped — only suppresses specific rule codes
        - phrase: "known-safe-deploy"
          rules:
            - PERM_005

        # Expiring — suppression expires on the given date
        - phrase: "sk-ant-placeholder-for-ci"
          expires: "2026-12-31"
          reason: "CI placeholder, ticket #456 — rotate before expiry"
    """

    phrase: str
    rules: list[str] = field(default_factory=list)  # empty = applies to all rules
    expires: str = ""  # ISO date "YYYY-MM-DD", empty = never expires
    reason: str = ""  # documentation / ticket reference (not used in matching)

    def is_expired(self) -> bool:
        """Return True if this suppression has passed its expiry date."""
        if not self.expires:
            return False
        try:
            return date.today() > date.fromisoformat(self.expires)
        except ValueError:
            return True  # malformed date — fail closed: treat as expired so suppression is inactive

    def suppresses(self, finding_code: str, matched_text: str) -> bool:
        """Return True if this entry suppresses the given finding."""
        if self.is_expired():
            return False
        if self.rules and finding_code not in self.rules:
            return False
        return self.phrase.lower() in matched_text.lower()


@dataclass
class ScannerConfig:
    allowlist: list[AllowlistEntry] = field(default_factory=list)
    disabled_rules: list[str] = field(default_factory=list)
    enabled_rules: list[str] = field(default_factory=list)  # whitelist — only these codes run
    severity_overrides: dict[str, str] = field(default_factory=dict)
    custom_scan_rules: list[ScanRule] = field(default_factory=list)
    rules_dirs: list[str] = field(default_factory=list)  # extra rule pack directories


@dataclass
class LinterConfig:
    disabled_rules: list[str] = field(default_factory=list)
    enabled_rules: list[str] = field(default_factory=list)  # whitelist — only these codes run
    custom_vague_verbs: list[str] = field(default_factory=list)
    custom_lint_rules: list[LintRule] = field(default_factory=list)
    rules_dirs: list[str] = field(default_factory=list)  # extra rule pack directories


@dataclass
class RoutingRule:
    """A single provider routing rule."""
    condition: str   # "contains_secrets" | "classification == X" | "*"
    provider: str


@dataclass
class RoutingConfig:
    """Local-first provider routing configuration.

    Example .promptgenie.yaml::

        routing:
          default: local
          rules:
            - if: classification == confidential
              provider: ollama
            - if: contains_secrets
              provider: ollama
            - if: "*"
              provider: anthropic
    """
    default: str = ""               # default provider name (empty = use spec/CLI)
    rules: list[RoutingRule] = field(default_factory=list)

    def resolve(
        self,
        *,
        classification: str = "",
        has_secrets: bool = False,
        provider_override: str | None = None,
    ) -> str | None:
        """Return the provider name to use, or None to fall back to spec/CLI."""
        if provider_override:
            return provider_override
        for rule in self.rules:
            cond = rule.condition.strip()
            if cond == "*":
                return rule.provider
            if cond == "contains_secrets" and has_secrets:
                return rule.provider
            if cond.startswith("classification =="):
                rhs = cond.split("==", 1)[1].strip().strip("'\"")
                if classification.lower() == rhs.lower():
                    return rule.provider
        return self.default or None


@dataclass
class SecurityConfig:
    """Security-level settings for the project.

    Example .promptgenie.yaml::

        security:
          airgap: true         # block all external provider calls
          block_secrets: true  # abort run if secrets detected in prompt
          redact_secrets: false # auto-redact instead of blocking
    """
    airgap: bool = False
    block_secrets: bool = False
    redact_secrets: bool = False


@dataclass
class WorkspaceConfig:
    """Project-level metadata block from the ``workspace:`` section."""
    name: str = ""
    version: str = ""
    team: str = ""
    description: str = ""
    policy: str = ""


@dataclass
class DefaultsConfig:
    """Default provider/model/target used when not specified per-run."""
    provider: str = ""
    model: str = ""
    target: str = ""


@dataclass
class PromptGenieConfig:
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    linter: LinterConfig = field(default_factory=LinterConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


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
            expires = str(item.get("expires", "")).strip()
            reason = str(item.get("reason", "")).strip()
            entries.append(
                AllowlistEntry(phrase=phrase, rules=rules, expires=expires, reason=reason)
            )
        else:
            raise ValueError(
                f"Allowlist entry must be a string or a mapping, got {type(item).__name__}: {item!r}"
            )
    return entries


_VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
_VALID_SEVERITY = {"HIGH", "MEDIUM", "LOW", "INFO"}


def _parse_custom_scan_rules(raw_rules: list[Any]) -> list[ScanRule]:
    from promptgenie.core.scanner import ScanRule, validate_pattern

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
            raise ValueError(
                f"Custom scan rule {rule_id!r}: invalid risk {risk!r}. "
                f"Must be one of {sorted(_VALID_RISK_LEVELS)}."
            )
        if confidence not in _VALID_CONFIDENCE:
            raise ValueError(
                f"Custom scan rule {rule_id!r}: invalid confidence {confidence!r}. "
                f"Must be one of {sorted(_VALID_CONFIDENCE)}."
            )
        try:
            validate_pattern(pattern, rule_id)
        except ValueError as exc:
            raise ValueError(f"Custom scan rule {exc}") from exc
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
    from promptgenie.core.scanner import validate_pattern

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
            raise ValueError(
                f"Custom lint rule {rule_id!r}: invalid severity {severity!r}. "
                f"Must be one of {sorted(_VALID_SEVERITY)}."
            )
        if confidence not in _VALID_CONFIDENCE:
            raise ValueError(
                f"Custom lint rule {rule_id!r}: invalid confidence {confidence!r}. "
                f"Must be one of {sorted(_VALID_CONFIDENCE)}."
            )
        try:
            validate_pattern(pattern, rule_id)
        except ValueError as exc:
            raise ValueError(f"Custom lint rule {exc}") from exc
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
        enabled_rules=[str(v) for v in raw.get("enabled_rules", [])],
        severity_overrides=overrides,
        custom_scan_rules=_parse_custom_scan_rules(raw.get("custom_rules", [])),
        rules_dirs=[str(v) for v in raw.get("rules_dirs", [])],
    )


def _parse_linter(raw: dict[str, Any]) -> LinterConfig:
    return LinterConfig(
        disabled_rules=[str(v) for v in raw.get("disabled_rules", [])],
        enabled_rules=[str(v) for v in raw.get("enabled_rules", [])],
        custom_vague_verbs=[str(v) for v in raw.get("custom_vague_verbs", [])],
        custom_lint_rules=_parse_custom_lint_rules(raw.get("custom_rules", [])),
        rules_dirs=[str(v) for v in raw.get("rules_dirs", [])],
    )


def _parse_routing(raw: dict[str, Any]) -> RoutingConfig:
    rules = []
    for r in raw.get("rules", []):
        if not isinstance(r, dict):
            continue
        cond = str(r.get("if", "*"))
        provider = str(r.get("provider", ""))
        if provider:
            rules.append(RoutingRule(condition=cond, provider=provider))
    return RoutingConfig(
        default=str(raw.get("default", "")),
        rules=rules,
    )


def _parse_security(raw: dict[str, Any]) -> SecurityConfig:
    return SecurityConfig(
        airgap=bool(raw.get("airgap", False)),
        block_secrets=bool(raw.get("block_secrets", False)),
        redact_secrets=bool(raw.get("redact_secrets", False)),
    )


def _parse_workspace(raw: dict[str, Any]) -> WorkspaceConfig:
    return WorkspaceConfig(
        name=str(raw.get("name", "")),
        version=str(raw.get("version", "")),
        team=str(raw.get("team", "")),
        description=str(raw.get("description", "")),
        policy=str(raw.get("policy", "")),
    )


def _parse_defaults(raw: dict[str, Any]) -> DefaultsConfig:
    return DefaultsConfig(
        provider=str(raw.get("provider", "")),
        model=str(raw.get("model", "")),
        target=str(raw.get("target", "")),
    )


# ---------------------------------------------------------------------------
# Workspace config validator
# ---------------------------------------------------------------------------

_TOP_LEVEL_KEYS = frozenset(
    {"$schema", "workspace", "defaults", "scanner", "linter", "routing", "security"}
)
_WORKSPACE_KEYS = frozenset({"name", "version", "team", "description", "policy"})
_DEFAULTS_KEYS = frozenset({"provider", "model", "target"})
_SCANNER_KEYS = frozenset(
    {"allowlist", "disabled_rules", "enabled_rules", "severity_overrides", "custom_rules", "rules_dirs"}
)
_LINTER_KEYS = frozenset(
    {"disabled_rules", "enabled_rules", "custom_vague_verbs", "custom_rules", "rules_dirs"}
)
_ROUTING_KEYS = frozenset({"default", "rules"})
_SECURITY_KEYS = frozenset({"airgap", "block_secrets", "redact_secrets"})
_VALID_RISK = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
_VALID_SEVERITY = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"})
_VALID_CONFIDENCE = frozenset({"HIGH", "MEDIUM", "LOW"})
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_workspace_config(raw: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Validate a raw .promptgenie.yaml dict.

    Returns ``(errors, warnings)`` — errors must be fixed, warnings are advisory.
    An empty error list means the file is valid.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(raw, dict):
        errors.append("Config file must be a YAML mapping at the top level.")
        return errors, warnings

    unknown = set(raw) - _TOP_LEVEL_KEYS
    for key in sorted(unknown):
        errors.append(f"Unknown top-level key: '{key}'")

    def _check_dict(section: str, value: Any, allowed: frozenset[str]) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            errors.append(f"'{section}' must be a mapping, got {type(value).__name__}.")
            return None
        for k in sorted(set(value) - allowed):
            errors.append(f"'{section}': unknown key '{k}'")
        return value

    def _check_str(path: str, value: Any) -> None:
        if not isinstance(value, str):
            errors.append(f"'{path}' must be a string, got {type(value).__name__}.")

    def _check_bool(path: str, value: Any) -> None:
        if not isinstance(value, bool):
            errors.append(f"'{path}' must be a boolean (true/false), got {type(value).__name__}.")

    def _check_list_of_str(path: str, value: Any) -> None:
        if not isinstance(value, list):
            errors.append(f"'{path}' must be a list, got {type(value).__name__}.")
            return
        for i, item in enumerate(value):
            if not isinstance(item, str):
                errors.append(f"'{path}[{i}]' must be a string, got {type(item).__name__}.")

    # --- workspace ---
    if "workspace" in raw:
        ws = _check_dict("workspace", raw["workspace"], _WORKSPACE_KEYS)
        if ws:
            for key in ("name", "version", "team", "description", "policy"):
                if key in ws:
                    _check_str(f"workspace.{key}", ws[key])
            if "name" in ws and isinstance(ws["name"], str) and not ws["name"].strip():
                warnings.append("'workspace.name' is blank — consider setting a project name.")

    # --- defaults ---
    if "defaults" in raw:
        df = _check_dict("defaults", raw["defaults"], _DEFAULTS_KEYS)
        if df:
            for key in ("provider", "model", "target"):
                if key in df:
                    _check_str(f"defaults.{key}", df[key])

    # --- scanner ---
    if "scanner" in raw:
        sc = _check_dict("scanner", raw["scanner"], _SCANNER_KEYS)
        if sc:
            for list_key in ("disabled_rules", "enabled_rules", "rules_dirs"):
                if list_key in sc:
                    _check_list_of_str(f"scanner.{list_key}", sc[list_key])

            if "severity_overrides" in sc:
                so = sc["severity_overrides"]
                if not isinstance(so, dict):
                    errors.append(f"'scanner.severity_overrides' must be a mapping.")
                else:
                    for code, level in so.items():
                        if not isinstance(level, str) or level.upper() not in _VALID_RISK:
                            errors.append(
                                f"'scanner.severity_overrides.{code}': invalid risk level {level!r}. "
                                f"Must be one of {sorted(_VALID_RISK)}."
                            )

            if "allowlist" in sc:
                _validate_allowlist("scanner.allowlist", sc["allowlist"], errors, warnings)

            if "custom_rules" in sc:
                _validate_custom_scan_rules("scanner.custom_rules", sc["custom_rules"], errors)

    # --- linter ---
    if "linter" in raw:
        li = _check_dict("linter", raw["linter"], _LINTER_KEYS)
        if li:
            for list_key in ("disabled_rules", "enabled_rules", "custom_vague_verbs", "rules_dirs"):
                if list_key in li:
                    _check_list_of_str(f"linter.{list_key}", li[list_key])

            if "custom_rules" in li:
                _validate_custom_lint_rules("linter.custom_rules", li["custom_rules"], errors)

    # --- routing ---
    if "routing" in raw:
        ro = _check_dict("routing", raw["routing"], _ROUTING_KEYS)
        if ro:
            if "default" in ro:
                _check_str("routing.default", ro["default"])
            if "rules" in ro:
                rules = ro["rules"]
                if not isinstance(rules, list):
                    errors.append("'routing.rules' must be a list.")
                else:
                    _ROUTING_RULE_KEYS = frozenset({"if", "provider"})
                    for i, rule in enumerate(rules):
                        if not isinstance(rule, dict):
                            errors.append(f"'routing.rules[{i}]' must be a mapping.")
                            continue
                        unknown_rk = set(rule) - _ROUTING_RULE_KEYS
                        for k in sorted(unknown_rk):
                            errors.append(f"'routing.rules[{i}]': unknown key '{k}'")
                        if "if" not in rule:
                            errors.append(f"'routing.rules[{i}]' is missing required key 'if'.")
                        if "provider" not in rule:
                            errors.append(
                                f"'routing.rules[{i}]' is missing required key 'provider'."
                            )

    # --- security ---
    if "security" in raw:
        se = _check_dict("security", raw["security"], _SECURITY_KEYS)
        if se:
            for key in ("airgap", "block_secrets", "redact_secrets"):
                if key in se:
                    _check_bool(f"security.{key}", se[key])
            if se.get("block_secrets") and se.get("redact_secrets"):
                warnings.append(
                    "'security.block_secrets' and 'security.redact_secrets' are both true — "
                    "block_secrets takes precedence; redact_secrets has no effect."
                )

    return errors, warnings


def _validate_allowlist(
    path: str, entries: Any, errors: list[str], warnings: list[str]
) -> None:
    if not isinstance(entries, list):
        errors.append(f"'{path}' must be a list.")
        return
    for i, entry in enumerate(entries):
        if isinstance(entry, str):
            if not entry.strip():
                warnings.append(f"'{path}[{i}]' is a blank string — allowlist entry has no effect.")
        elif isinstance(entry, dict):
            if "phrase" not in entry:
                errors.append(f"'{path}[{i}]' is missing required key 'phrase'.")
            elif not isinstance(entry["phrase"], str) or not entry["phrase"].strip():
                errors.append(f"'{path}[{i}].phrase' must be a non-empty string.")
            if "expires" in entry:
                exp = entry["expires"]
                if not isinstance(exp, str) or not _ISO_DATE_RE.match(exp):
                    errors.append(
                        f"'{path}[{i}].expires' must be an ISO date string (YYYY-MM-DD), got {exp!r}."
                    )
            unknown = set(entry) - {"phrase", "rules", "expires", "reason"}
            for k in sorted(unknown):
                errors.append(f"'{path}[{i}]': unknown key '{k}'")
        else:
            errors.append(
                f"'{path}[{i}]' must be a string or mapping, got {type(entry).__name__}."
            )


def _validate_custom_scan_rules(path: str, rules: Any, errors: list[str]) -> None:
    if not isinstance(rules, list):
        errors.append(f"'{path}' must be a list.")
        return
    _SCAN_RULE_KEYS = frozenset({
        "id", "pattern", "category", "risk", "confidence",
        "message", "recommendation", "false_positive_note", "use_original_text",
    })
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"'{path}[{i}]' must be a mapping.")
            continue
        unknown = set(rule) - _SCAN_RULE_KEYS
        for k in sorted(unknown):
            errors.append(f"'{path}[{i}]': unknown key '{k}'")
        if "id" not in rule or not str(rule.get("id", "")).strip():
            errors.append(f"'{path}[{i}]' is missing required key 'id'.")
        if "pattern" not in rule or not str(rule.get("pattern", "")).strip():
            errors.append(f"'{path}[{i}]' is missing required key 'pattern'.")
        if "risk" in rule and str(rule["risk"]).upper() not in _VALID_RISK:
            errors.append(
                f"'{path}[{i}].risk': invalid value {rule['risk']!r}. "
                f"Must be one of {sorted(_VALID_RISK)}."
            )
        if "confidence" in rule and str(rule["confidence"]).upper() not in _VALID_CONFIDENCE:
            errors.append(
                f"'{path}[{i}].confidence': invalid value {rule['confidence']!r}. "
                f"Must be one of {sorted(_VALID_CONFIDENCE)}."
            )


def _validate_custom_lint_rules(path: str, rules: Any, errors: list[str]) -> None:
    if not isinstance(rules, list):
        errors.append(f"'{path}' must be a list.")
        return
    _LINT_RULE_KEYS = frozenset({
        "id", "pattern", "category", "severity", "confidence",
        "message", "suggestion", "false_positive_note", "negate", "requires_agentic",
    })
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"'{path}[{i}]' must be a mapping.")
            continue
        unknown = set(rule) - _LINT_RULE_KEYS
        for k in sorted(unknown):
            errors.append(f"'{path}[{i}]': unknown key '{k}'")
        if "id" not in rule or not str(rule.get("id", "")).strip():
            errors.append(f"'{path}[{i}]' is missing required key 'id'.")
        if "pattern" not in rule or not str(rule.get("pattern", "")).strip():
            errors.append(f"'{path}[{i}]' is missing required key 'pattern'.")
        if "severity" in rule and str(rule["severity"]).upper() not in _VALID_SEVERITY:
            errors.append(
                f"'{path}[{i}].severity': invalid value {rule['severity']!r}. "
                f"Must be one of {sorted(_VALID_SEVERITY)}."
            )
        if "confidence" in rule and str(rule["confidence"]).upper() not in _VALID_CONFIDENCE:
            errors.append(
                f"'{path}[{i}].confidence': invalid value {rule['confidence']!r}. "
                f"Must be one of {sorted(_VALID_CONFIDENCE)}."
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

    raw = safe_read_yaml(config_path) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Config file {config_path} must be a YAML mapping.")

    return PromptGenieConfig(
        workspace=_parse_workspace(raw.get("workspace", {})),
        defaults=_parse_defaults(raw.get("defaults", {})),
        scanner=_parse_scanner(raw.get("scanner", {})),
        linter=_parse_linter(raw.get("linter", {})),
        routing=_parse_routing(raw.get("routing", {})),
        security=_parse_security(raw.get("security", {})),
    )


def _find_config() -> Path | None:
    """Walk from cwd upward looking for .promptgenie.yaml."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / ".promptgenie.yaml"
        if candidate.exists():
            return candidate
    return None
