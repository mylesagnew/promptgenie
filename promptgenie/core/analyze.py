"""analyze.py — unified finding model and aggregate analysis pipeline.

Combines lint, scan, and policy evaluation into a single pass with a
normalised ``Finding`` dataclass that maps to SARIF-compatible fields.

Finding categories (OWASP LLM Top 10 aligned)
----------------------------------------------
  prompt-injection        — instruction override, indirect injection
  data-leakage            — PII, secrets, internal hostnames in prompt text
  secret-exposure         — API keys, tokens, credentials
  unsafe-agent-permission — unrestricted filesystem, network, code exec
  destructive-action      — mass delete, db drop, production deploy without gate
  compliance              — PCI, HIPAA, GDPR violations
  quality                 — vague verbs, missing structure, over-broad scope

Public API
----------
  ``analyze(text, file_path, config)``  → AnalyzeResult
  ``Finding``                           — unified finding dataclass
  ``AnalyzeResult``                     — dataclass with findings and summary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from promptgenie.core.linter import LintResult, lint
from promptgenie.core.scanner import ScanResult, scan

# ---------------------------------------------------------------------------
# Category normalisation maps
# ---------------------------------------------------------------------------

_SCAN_CATEGORY_MAP: dict[str, str] = {
    "secret": "secret-exposure",
    "data-leakage": "data-leakage",
    "injection": "prompt-injection",
    "permission": "unsafe-agent-permission",
    "rag": "prompt-injection",
    "obfuscation": "prompt-injection",
}

_LINT_CATEGORY_MAP: dict[str, str] = {
    "agentic_risk": "unsafe-agent-permission",
    "structure": "quality",
    "task_quality": "quality",
}

_RISK_TO_SEVERITY: dict[str, str] = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFO": "INFO",
    "NONE": "INFO",
}

_LINT_SEV_MAP: dict[str, str] = {
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFO": "INFO",
}

# Special overrides: which lint categories are destructive-action
_DESTRUCTIVE_LINT_CODES = {"AGENT_005", "AGENT_006", "AGENT_007"}


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


@dataclass
class Location:
    file: str = ""
    line: int = 0
    col: int = 0


@dataclass
class Finding:
    code: str
    title: str
    severity: str          # CRITICAL | HIGH | MEDIUM | LOW | INFO
    category: str          # prompt-injection | data-leakage | secret-exposure |
    #                        unsafe-agent-permission | destructive-action | compliance | quality
    location: Location
    evidence: str
    remediation: str
    confidence: str        # HIGH | MEDIUM | LOW
    tags: list[str] = field(default_factory=list)
    source: str = "scan"   # scan | lint | policy | custom


@dataclass
class AnalyzeResult:
    findings: list[Finding] = field(default_factory=list)
    lint_score: int = 100
    scan_risk: str = "NONE"

    @property
    def severity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts

    @property
    def overall_risk(self) -> str:
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            if any(f.severity == level for f in self.findings):
                return level
        return "NONE"

    def by_category(self, category: str) -> list[Finding]:
        return [f for f in self.findings if f.category == category]

    def by_severity(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------


def analyze(
    text: str,
    file_path: str = "<stdin>",
    scanner_config: Any = None,
    linter_config: Any = None,
    include_lint: bool = True,
    include_scan: bool = True,
) -> AnalyzeResult:
    """Run lint + scan on *text* and return a unified ``AnalyzeResult``."""
    findings: list[Finding] = []

    scan_result: ScanResult | None = None
    lint_result: LintResult | None = None

    if include_scan:
        scan_result = scan(text, config=scanner_config)
        for sf in scan_result.findings:
            raw_cat = sf.category or "secret"
            category = _SCAN_CATEGORY_MAP.get(raw_cat, raw_cat)
            severity = sf.risk
            findings.append(Finding(
                code=sf.code,
                title=sf.message,
                severity=severity,
                category=category,
                location=Location(file=file_path, line=sf.line, col=sf.col),
                evidence=sf.matched_text,
                remediation=sf.recommendation,
                confidence=sf.confidence,
                tags=[raw_cat],
                source="scan",
            ))

    if include_lint:
        lint_result = lint(text, config=linter_config)
        for li in lint_result.issues:
            raw_cat = _lint_category_for_code(li.code)
            severity = _LINT_SEV_MAP.get(li.severity, li.severity)
            findings.append(Finding(
                code=li.code,
                title=li.message,
                severity=severity,
                category=raw_cat,
                location=Location(file=file_path, line=li.line, col=li.col),
                evidence="",
                remediation=li.suggestion,
                confidence=li.confidence,
                tags=["quality"],
                source="lint",
            ))

    return AnalyzeResult(
        findings=findings,
        lint_score=lint_result.score if lint_result else 100,
        scan_risk=scan_result.risk_level if scan_result else "NONE",
    )


def _lint_category_for_code(code: str) -> str:
    if code in _DESTRUCTIVE_LINT_CODES:
        return "destructive-action"
    # Use prefix-based mapping
    for prefix, cat in [
        ("AGENT_", "unsafe-agent-permission"),
        ("STRUCT_", "quality"),
        ("TASK_", "quality"),
    ]:
        if code.startswith(prefix):
            return cat
    return "quality"


# ---------------------------------------------------------------------------
# SARIF serialiser
# ---------------------------------------------------------------------------


def findings_to_sarif(result: AnalyzeResult, file_path: str = "<stdin>") -> dict:
    """Convert an AnalyzeResult to a SARIF 2.1.0 dict."""
    rules = []
    seen_codes: set[str] = set()
    results = []

    for finding in result.findings:
        if finding.code not in seen_codes:
            seen_codes.add(finding.code)
            rules.append({
                "id": finding.code,
                "name": finding.title[:80],
                "shortDescription": {"text": finding.title},
                "fullDescription": {"text": finding.remediation or finding.title},
                "properties": {
                    "category": finding.category,
                    "tags": finding.tags,
                },
            })

        sarif_level = {
            "CRITICAL": "error",
            "HIGH": "error",
            "MEDIUM": "warning",
            "LOW": "note",
            "INFO": "none",
        }.get(finding.severity, "note")

        results.append({
            "ruleId": finding.code,
            "level": sarif_level,
            "message": {"text": finding.title},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": file_path},
                        "region": {
                            "startLine": max(1, finding.location.line or 1),
                            "startColumn": max(1, finding.location.col or 1),
                        },
                    }
                }
            ],
            "properties": {
                "category": finding.category,
                "severity": finding.severity,
                "confidence": finding.confidence,
                "source": finding.source,
                "evidence": finding.evidence,
                "remediation": finding.remediation,
            },
        })

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "promptgenie-analyze",
                        "version": "1.0.0",
                        "informationUri": "https://github.com/promptgenie/promptgenie",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
