"""
formatters.py — structured output serialisers for lint and scan results.

Supports:
  json   — machine-readable dict/list suitable for CI tooling and scripts
  sarif  — Static Analysis Results Interchange Format v2.1.0
           consumed by GitHub Code Scanning, VS Code SARIF viewer, Azure DevOps, etc.

SARIF spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promptgenie.core.linter import LintResult
    from promptgenie.core.scanner import ScanResult

TOOL_NAME = "promptgenie"
TOOL_VERSION = "1.0.0"
TOOL_URI = "https://github.com/mylesagnew/promptgenie"

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
)

# Map our severity/risk levels to SARIF levels
SEVERITY_TO_SARIF = {
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "note",
    "INFO": "none",
}

RISK_TO_SARIF = {
    "CRITICAL": "error",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "note",
}


# ── JSON formatters ──────────────────────────────────────────────────────────


def lint_to_json(result: LintResult, prompt_path: str = "") -> str:
    data = {
        "tool": TOOL_NAME,
        "command": "lint",
        "file": prompt_path,
        "score": result.score,
        "issue_count": len(result.issues),
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity,
                "message": issue.message,
                "suggestion": issue.suggestion,
            }
            for issue in result.issues
        ],
    }
    return json.dumps(data, indent=2)


def scan_to_json(result: ScanResult, prompt_path: str = "") -> str:
    data = {
        "tool": TOOL_NAME,
        "command": "scan",
        "file": prompt_path,
        "risk_level": result.risk_level,
        "finding_count": len(result.findings),
        "findings": [
            {
                "code": f.code,
                "risk": f.risk,
                "message": f.message,
                "detail": f.detail,
                "recommendation": f.recommendation,
            }
            for f in result.findings
        ],
    }
    return json.dumps(data, indent=2)


# ── SARIF formatters ─────────────────────────────────────────────────────────


def _sarif_envelope(runs: list[dict]) -> dict:
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": runs,
    }


def _sarif_tool(rules: list[dict]) -> dict:
    return {
        "driver": {
            "name": TOOL_NAME,
            "version": TOOL_VERSION,
            "informationUri": TOOL_URI,
            "rules": rules,
        }
    }


def _sarif_location(prompt_path: str, region: dict | None = None) -> dict:
    loc: dict = {
        "physicalLocation": {
            "artifactLocation": {
                "uri": prompt_path or "unknown",
                "uriBaseId": "%SRCROOT%",
            }
        }
    }
    if region:
        loc["physicalLocation"]["region"] = region
    return loc


def lint_to_sarif(result: LintResult, prompt_path: str = "") -> str:
    # Build rule registry from unique codes
    seen_codes: dict[str, dict] = {}
    for issue in result.issues:
        if issue.code not in seen_codes:
            seen_codes[issue.code] = {
                "id": issue.code,
                "name": issue.code,
                "shortDescription": {"text": issue.message},
                "fullDescription": {"text": issue.suggestion or issue.message},
                "defaultConfiguration": {"level": SEVERITY_TO_SARIF.get(issue.severity, "warning")},
                "helpUri": TOOL_URI,
                "properties": {"tags": ["prompt-lint"]},
            }

    rules = list(seen_codes.values())

    results = [
        {
            "ruleId": issue.code,
            "level": SEVERITY_TO_SARIF.get(issue.severity, "warning"),
            "message": {"text": f"{issue.message} {issue.suggestion}".strip()},
            "locations": [_sarif_location(prompt_path)],
        }
        for issue in result.issues
    ]

    sarif = _sarif_envelope(
        [
            {
                "tool": _sarif_tool(rules),
                "results": results,
                "artifacts": [{"location": {"uri": prompt_path or "unknown"}}],
            }
        ]
    )
    return json.dumps(sarif, indent=2)


def scan_to_sarif(result: ScanResult, prompt_path: str = "") -> str:
    seen_codes: dict[str, dict] = {}
    for f in result.findings:
        if f.code not in seen_codes:
            seen_codes[f.code] = {
                "id": f.code,
                "name": f.code,
                "shortDescription": {"text": f.message},
                "fullDescription": {"text": f.recommendation or f.message},
                "defaultConfiguration": {"level": RISK_TO_SARIF.get(f.risk, "warning")},
                "helpUri": TOOL_URI,
                "properties": {"tags": ["prompt-security", f"risk:{f.risk.lower()}"]},
            }

    rules = list(seen_codes.values())

    results = [
        {
            "ruleId": f.code,
            "level": RISK_TO_SARIF.get(f.risk, "warning"),
            "message": {"text": f"{f.message} {f.recommendation}".strip()},
            "locations": [_sarif_location(prompt_path)],
        }
        for f in result.findings
    ]

    sarif = _sarif_envelope(
        [
            {
                "tool": _sarif_tool(rules),
                "results": results,
                "artifacts": [{"location": {"uri": prompt_path or "unknown"}}],
            }
        ]
    )
    return json.dumps(sarif, indent=2)
