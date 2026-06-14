"""policy_engine.py — Policy-as-code v2 engine.

Policy file discovery chain (first found wins)::

  .promptgenie.policy.yaml   (project root)
  promptgenie.policy.yaml    (cwd)
  ~/.config/promptgenie/policy.yaml  (user global)

Policy file format::

  version: 1

  # Security thresholds
  max_risk: HIGH           # block if any finding at or above this level
  max_findings: 0          # 0 = block on any qualifying finding
  min_score: 0             # 0 = lint score not checked

  # Provider access control
  allowed_providers:
    - anthropic
    - ollama

  # External send gate (requires --yes flag or airgap)
  external_model_send:
    require_clean_scan: true   # scan must pass before any external send
    allowed_providers:
      - anthropic
    block_on_classification:
      - confidential
      - restricted

  # Rule bundles — load extra rule packs by name or path
  rule_packs:
    - security-baseline
    - ./rules/custom-rules.yaml

  # Per-category severity overrides
  severity_overrides:
    LEAK_EMAIL: LOW

Public API
----------
  ``discover_policy_file()``          → Path | None
  ``load_policy(path)``               → PolicyConfig
  ``evaluate_policy(result, config)`` → PolicyEvaluation
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DISCOVERY_PATHS = [
    Path(".promptgenie.policy.yaml"),
    Path("promptgenie.policy.yaml"),
    Path("~/.config/promptgenie/policy.yaml").expanduser(),
]


# ---------------------------------------------------------------------------
# PolicyConfig dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExternalSendPolicy:
    require_clean_scan: bool = True
    allowed_providers: list[str] = field(default_factory=list)
    block_on_classification: list[str] = field(default_factory=list)


@dataclass
class PolicyConfig:
    version: int = 1
    max_risk: str = "HIGH"
    max_findings: int = 0
    min_score: int = 0
    allowed_providers: list[str] = field(default_factory=list)
    external_model_send: ExternalSendPolicy = field(default_factory=ExternalSendPolicy)
    rule_packs: list[str] = field(default_factory=list)
    severity_overrides: dict[str, str] = field(default_factory=dict)
    source_path: Path | None = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# PolicyEvaluation dataclass
# ---------------------------------------------------------------------------


@dataclass
class PolicyViolation:
    rule: str
    message: str
    detail: str = ""


@dataclass
class PolicyEvaluation:
    passed: bool
    violations: list[PolicyViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Per-rule explain output (populated when explain=True)
    explain_lines: list[str] = field(default_factory=list)

    def add_violation(self, rule: str, message: str, detail: str = "") -> None:
        self.violations.append(PolicyViolation(rule=rule, message=message, detail=detail))
        self.passed = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_policy_file() -> Path | None:
    """Find the first policy file in the discovery chain."""
    for path in _DISCOVERY_PATHS:
        if path.exists():
            return path
    return None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_policy(path: str | Path | None = None) -> PolicyConfig:
    """Load a PolicyConfig from *path*, or discover automatically if None."""
    if path is None:
        found = discover_policy_file()
        if found is None:
            return PolicyConfig()
        path = found

    p = Path(path)
    if not p.exists():
        from promptgenie.core.errors import EXIT_USAGE, PromptGenieError
        raise PromptGenieError(f"Policy file not found: {p}", code=EXIT_USAGE)

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return _build_policy(raw, source_path=p)


def _build_policy(raw: dict[str, Any], source_path: Path | None = None) -> PolicyConfig:
    ext_raw = raw.get("external_model_send") or {}
    ext = ExternalSendPolicy(
        require_clean_scan=bool(ext_raw.get("require_clean_scan", True)),
        allowed_providers=[str(p) for p in ext_raw.get("allowed_providers", [])],
        block_on_classification=[str(c) for c in ext_raw.get("block_on_classification", [])],
    )
    return PolicyConfig(
        version=int(raw.get("version", 1)),
        max_risk=str(raw.get("max_risk", "HIGH")).upper(),
        max_findings=int(raw.get("max_findings", 0)),
        min_score=int(raw.get("min_score", 0)),
        allowed_providers=[str(p) for p in raw.get("allowed_providers", [])],
        external_model_send=ext,
        rule_packs=list(raw.get("rule_packs") or []),
        severity_overrides={str(k): str(v).upper()
                             for k, v in (raw.get("severity_overrides") or {}).items()},
        source_path=source_path,
    )


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

_RISK_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}


def evaluate_policy(
    analyze_result: Any,
    policy: PolicyConfig,
    *,
    provider: str | None = None,
    classification: str | None = None,
    explain: bool = False,
) -> PolicyEvaluation:
    """Evaluate an AnalyzeResult against a PolicyConfig.

    Parameters
    ----------
    analyze_result:
        ``AnalyzeResult`` from ``promptgenie.core.analyze.analyze()``.
    policy:
        ``PolicyConfig`` loaded from a policy file.
    provider:
        Provider name being used (for allowed_providers gate).
    classification:
        Content classification declared in the spec (for external_send gate).
    explain:
        If True, populate ``explain_lines`` with a human-readable rule trace.
    """
    ev = PolicyEvaluation(passed=True)
    lines = ev.explain_lines

    def _explain(msg: str) -> None:
        if explain:
            lines.append(msg)

    # ── max_risk threshold — applies to scan (security) findings only ─────────
    # Lint quality findings are governed by min_score, not max_risk.
    max_order = _RISK_ORDER.get(policy.max_risk, 1)
    qualifying = [
        f for f in analyze_result.findings
        if getattr(f, "source", "scan") == "scan"
        and _RISK_ORDER.get(f.severity, 99) <= max_order
    ]
    _explain(
        f"[max_risk={policy.max_risk}] "
        f"{len(qualifying)} finding(s) at or above threshold"
        + (" ✓" if not qualifying else " ✗")
    )
    if qualifying and (policy.max_findings == 0 or len(qualifying) > policy.max_findings):
        threshold_str = "any" if policy.max_findings == 0 else str(policy.max_findings)
        ev.add_violation(
            rule="max_risk",
            message=(
                f"{len(qualifying)} finding(s) at or above {policy.max_risk} "
                f"(threshold: {threshold_str})"
            ),
            detail="; ".join(f"{f.code}:{f.severity}" for f in qualifying[:5]),
        )

    # ── min_score threshold ──────────────────────────────────────────────────
    if policy.min_score > 0:
        score = analyze_result.lint_score
        _explain(
            f"[min_score={policy.min_score}] lint score={score}"
            + (" ✓" if score >= policy.min_score else " ✗")
        )
        if score < policy.min_score:
            ev.add_violation(
                rule="min_score",
                message=f"Lint score {score}/100 is below minimum {policy.min_score}",
            )

    # ── allowed_providers gate ───────────────────────────────────────────────
    if policy.allowed_providers and provider:
        allowed = [p.lower() for p in policy.allowed_providers]
        _explain(
            f"[allowed_providers={policy.allowed_providers}] provider={provider}"
            + (" ✓" if provider.lower() in allowed else " ✗")
        )
        if provider.lower() not in allowed:
            ev.add_violation(
                rule="allowed_providers",
                message=f"Provider '{provider}' is not in the allowed providers list.",
                detail=f"Allowed: {', '.join(policy.allowed_providers)}",
            )

    # ── external_model_send gate ─────────────────────────────────────────────
    ext = policy.external_model_send
    if ext.block_on_classification and classification:
        blocked = [c.lower() for c in ext.block_on_classification]
        _explain(
            f"[external_model_send.block_on_classification] classification={classification}"
            + (" ✗" if classification.lower() in blocked else " ✓")
        )
        if classification.lower() in blocked:
            ev.add_violation(
                rule="external_model_send.classification",
                message=(
                    f"Classification '{classification}' is blocked from external provider sends."
                ),
                detail=f"Blocked classifications: {', '.join(ext.block_on_classification)}",
            )

    if ext.require_clean_scan and provider:
        is_local = _is_local_provider(provider)
        if not is_local:
            scan_failed = any(
                _RISK_ORDER.get(f.severity, 99) <= _RISK_ORDER.get("HIGH", 1)
                for f in analyze_result.findings
                if f.source == "scan"
            )
            _explain(
                f"[external_model_send.require_clean_scan] "
                f"provider={provider} is_local={is_local} scan_failed={scan_failed}"
                + (" ✗" if scan_failed else " ✓")
            )
            if scan_failed:
                ev.add_violation(
                    rule="external_model_send.require_clean_scan",
                    message=(
                        "External provider send blocked: scan has HIGH+ findings. "
                        "Run 'promptgenie redact' to sanitise the prompt."
                    ),
                )

    return ev


def _is_local_provider(name: str) -> bool:
    """Heuristic: is this provider a local/offline one?"""
    local_names = {"ollama", "localai", "lm-studio", "lmstudio", "vllm", "llamafile"}
    return name.lower() in local_names
