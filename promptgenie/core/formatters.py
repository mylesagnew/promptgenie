"""
formatters.py — structured output serialisers for lint and scan results.

Supports:
  json   — machine-readable dict/list suitable for CI tooling and scripts
  sarif  — Static Analysis Results Interchange Format v2.1.0
           consumed by GitHub Code Scanning, VS Code SARIF viewer, Azure DevOps, etc.

Also provides multi-file aggregation helpers:
  multi_scan_to_json()  — aggregate JSON for directory/zip scans
  multi_scan_to_sarif() — aggregate SARIF for directory/zip scans

SARIF spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promptgenie.core.linter import LintResult
    from promptgenie.core.llm_analyzer import LLMAnalysisResult
    from promptgenie.core.scanner import ScanResult

TOOL_NAME = "promptgenie"
SCHEMA_VERSION = "1.0"

try:
    TOOL_VERSION = version("promptgenie")
except PackageNotFoundError:
    TOOL_VERSION = "0.0.0"

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
    "NONE": "none",
}


# ── JSON formatters ──────────────────────────────────────────────────────────


def lint_to_json(result: LintResult, prompt_path: str = "") -> str:
    data = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "command": "lint",
        "file": prompt_path,
        "score": result.score,
        "issue_count": len(result.issues),
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity,
                "confidence": issue.confidence,
                "line": issue.line,
                "col": issue.col,
                "message": issue.message,
                "suggestion": issue.suggestion,
            }
            for issue in result.issues
        ],
    }
    return json.dumps(data, indent=2)


def scan_to_json(result: ScanResult, prompt_path: str = "") -> str:
    data = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "command": "scan",
        "file": prompt_path,
        "risk_level": result.risk_level,
        "finding_count": len(result.findings),
        "findings": [
            {
                "code": f.code,
                "category": f.category,
                "source": f.source,
                "risk": f.risk,
                "confidence": f.confidence,
                "line": f.line,
                "col": f.col,
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


def _sarif_location(prompt_path: str, line: int = 0, col: int = 0) -> dict:
    loc: dict = {
        "physicalLocation": {
            "artifactLocation": {
                "uri": prompt_path or "unknown",
                "uriBaseId": "%SRCROOT%",
            }
        }
    }
    if line > 0:
        loc["physicalLocation"]["region"] = {
            "startLine": line,
            "startColumn": max(col, 1),
        }
    return loc


def lint_to_sarif(result: LintResult, prompt_path: str = "") -> str:
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
                "properties": {
                    "tags": ["prompt-lint"],
                    "confidence": issue.confidence,
                },
            }

    rules = list(seen_codes.values())

    results = [
        {
            "ruleId": issue.code,
            "level": SEVERITY_TO_SARIF.get(issue.severity, "warning"),
            "message": {"text": f"{issue.message} {issue.suggestion}".strip()},
            "locations": [_sarif_location(prompt_path, issue.line, issue.col)],
            "properties": {"confidence": issue.confidence},
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
                "properties": {
                    "tags": ["prompt-security", f"risk:{f.risk.lower()}"],
                    "confidence": f.confidence,
                },
            }

    rules = list(seen_codes.values())

    results = [
        {
            "ruleId": f.code,
            "level": RISK_TO_SARIF.get(f.risk, "warning"),
            "message": {"text": f"{f.message} {f.recommendation}".strip()},
            "locations": [_sarif_location(prompt_path, f.line, f.col)],
            "properties": {"confidence": f.confidence},
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


# ── Multi-file aggregation ────────────────────────────────────────────────────


def multi_scan_to_json(
    file_results: list[tuple[str, ScanResult]],
    llm_results: list[LLMAnalysisResult] | None = None,
) -> str:
    """Aggregate scan results from multiple files into a single JSON document."""
    llm_map: dict[str, LLMAnalysisResult] = {}
    if llm_results:
        for lr in llm_results:
            llm_map[lr.file_path] = lr

    total_findings = 0
    files_data = []
    for file_path, result in file_results:
        findings_data = [
            {
                "code": f.code,
                "category": f.category,
                "source": f.source,
                "risk": f.risk,
                "confidence": f.confidence,
                "line": f.line,
                "col": f.col,
                "message": f.message,
                "detail": f.detail,
                "recommendation": f.recommendation,
            }
            for f in result.findings
        ]
        total_findings += len(findings_data)

        file_entry: dict = {
            "file": file_path,
            "risk_level": result.risk_level,
            "finding_count": len(findings_data),
            "findings": findings_data,
        }

        llm_result = llm_map.get(file_path)
        if llm_result is not None:
            file_entry["llm"] = {
                "skipped": llm_result.skipped,
                "skip_reason": llm_result.skip_reason if llm_result.skipped else None,
                "model": llm_result.model,
                "chars_analyzed": llm_result.chars_analyzed,
                "redaction_count": llm_result.redaction_count,
                "findings": [
                    {
                        "category": lf.category,
                        "severity": lf.severity,
                        "message": lf.message,
                        "evidence": lf.evidence,
                        "recommendation": lf.recommendation,
                    }
                    for lf in llm_result.findings
                ],
            }

        files_data.append(file_entry)

    risk_levels = [sr.risk_level for _, sr in file_results]
    aggregate_risk = _aggregate_risk(risk_levels)

    data = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "command": "scan",
        "file_count": len(file_results),
        "total_findings": total_findings,
        "aggregate_risk": aggregate_risk,
        "files": files_data,
    }
    return json.dumps(data, indent=2)


def multi_scan_to_sarif(
    file_results: list[tuple[str, ScanResult]],
) -> str:
    """Aggregate scan results from multiple files into a single SARIF 2.1.0 document."""
    seen_codes: dict[str, dict] = {}
    all_results = []
    artifacts = []

    for file_path, result in file_results:
        artifacts.append({"location": {"uri": file_path or "unknown"}})

        for f in result.findings:
            if f.code not in seen_codes:
                seen_codes[f.code] = {
                    "id": f.code,
                    "name": f.code,
                    "shortDescription": {"text": f.message},
                    "fullDescription": {"text": f.recommendation or f.message},
                    "defaultConfiguration": {"level": RISK_TO_SARIF.get(f.risk, "warning")},
                    "helpUri": TOOL_URI,
                    "properties": {
                        "tags": ["prompt-security", f"risk:{f.risk.lower()}"],
                        "confidence": f.confidence,
                    },
                }

            all_results.append(
                {
                    "ruleId": f.code,
                    "level": RISK_TO_SARIF.get(f.risk, "warning"),
                    "message": {"text": f"{f.message} {f.recommendation}".strip()},
                    "locations": [_sarif_location(file_path, f.line, f.col)],
                    "properties": {"confidence": f.confidence},
                }
            )

    sarif = _sarif_envelope(
        [
            {
                "tool": _sarif_tool(list(seen_codes.values())),
                "results": all_results,
                "artifacts": artifacts,
            }
        ]
    )
    return json.dumps(sarif, indent=2)


def _aggregate_risk(risk_levels: Sequence[str]) -> str:
    """Return the highest risk level from a list, or 'NONE' if empty."""
    order = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    if not risk_levels:
        return "NONE"
    return max(risk_levels, key=lambda r: order.get(r, 0))
