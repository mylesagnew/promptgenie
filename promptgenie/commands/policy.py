"""policy.py — Policy-as-code v2 gate command.

Uses policy_engine.py for discovery, evaluation, and explain mode.
Also supports backward-compatible --max-risk / --min-score inline overrides.

Exit codes:
    0  — prompt passes all policy rules
    1  — one or more policy rules violated
    2  — usage / configuration error
"""

from __future__ import annotations

import json
import sys

import click

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE, PromptGenieError
from promptgenie.core.fileio import safe_read_text
from promptgenie.renderers.rich import console, diag_console

# Risk level ordering used by the inline gate helper
_RISK_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _risk_at_or_above(level: str, threshold: str) -> bool:
    """Return True if *level* is at or above *threshold* in the risk scale.

    Unknown levels (not in the standard set) are treated as below everything
    and will never breach a threshold.
    """
    level_order = _RISK_ORDER.get(level, -1)
    if level_order < 0:
        return False
    threshold_order = _RISK_ORDER.get(threshold, -1)
    return level_order >= threshold_order


@click.command("policy")
@click.argument("file", type=click.Path(exists=True, readable=True))
# Inline threshold overrides (backward-compat + common-case convenience)
@click.option("--max-risk",
              type=click.Choice(["CRITICAL", "HIGH", "MEDIUM", "LOW"], case_sensitive=False),
              default=None,
              help="Override max_risk from policy file. Fail if any finding is at or above this level.")
@click.option("--max-findings", type=int, default=None,
              help="Override max_findings from policy file.")
@click.option("--min-score", type=int, default=None,
              help="Override min_score from policy file.")
# Policy source
@click.option("--policy-file", "policy_path", default=None, type=click.Path(),
              help="Explicit policy file path. Skips auto-discovery.")
@click.option("--no-policy-file", is_flag=True,
              help="Ignore any discovered/configured policy file; use inline flags only.")
# Provider / classification gates
@click.option("--provider", default=None,
              help="Provider name to check against allowed_providers gate.")
@click.option("--classification", default=None,
              help="Content classification (public|internal|confidential|restricted) "
                   "to check against external_model_send gate.")
# Explain / output
@click.option("--explain", is_flag=True,
              help="Print a per-rule evaluation trace (why each rule passed or failed).")
@click.option("--format", "output_format",
              type=click.Choice(["text", "json", "sarif"], case_sensitive=False),
              default="text", show_default=True,
              help="Output format.")
@click.option("--config", "config_path", default=None,
              help="Path to .promptgenie.yaml config file.")
@click.option("--no-config", is_flag=True,
              help="Ignore any .promptgenie.yaml config file.")
def policy(
    file: str,
    max_risk: str | None,
    max_findings: int | None,
    min_score: int | None,
    policy_path: str | None,
    no_policy_file: bool,
    provider: str | None,
    classification: str | None,
    explain: bool,
    output_format: str,
    config_path: str | None,
    no_config: bool,
) -> None:
    """Policy-as-code gate — analyse a prompt and exit 1 if policy is violated.

    Auto-discovers .promptgenie.policy.yaml → promptgenie.policy.yaml →
    ~/.config/promptgenie/policy.yaml. Inline flags override discovered values.

    \b
    Examples:
      promptgenie policy prompt.md
      promptgenie policy prompt.md --max-risk HIGH --min-score 70
      promptgenie policy prompt.md --policy-file team-policy.yaml --explain
      promptgenie policy prompt.md --provider anthropic --classification confidential
      promptgenie policy prompt.md --format json | jq '.passed'
    """
    from promptgenie.core.analyze import analyze
    from promptgenie.core.config import PromptGenieConfig, load_config
    from promptgenie.core.policy_engine import (
        PolicyConfig,
        discover_policy_file,
        evaluate_policy,
        load_policy,
    )

    # ── Load promptgenie config ─────────────────────────────────────────────
    pg_cfg: PromptGenieConfig
    if no_config:
        pg_cfg = PromptGenieConfig()
    elif config_path is not None:
        # Explicit path given — error on failure (exit 2)
        try:
            pg_cfg = load_config(config_path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            diag_console.print(f"[red]Error:[/red] Cannot load config {config_path!r}: {exc}")
            raise SystemExit(EXIT_USAGE)
        except Exception as exc:
            diag_console.print(f"[red]Error:[/red] Cannot load config {config_path!r}: {exc}")
            raise SystemExit(EXIT_USAGE)
    else:
        # Auto-discovery — fall back to defaults on error
        try:
            pg_cfg = load_config(None)
        except Exception:
            pg_cfg = PromptGenieConfig()

    # ── Read prompt ─────────────────────────────────────────────────────────
    try:
        prompt_text = safe_read_text(file)
    except (OSError, ValueError) as exc:
        diag_console.print(f"[red]Error:[/red] Cannot read {file!r}: {exc}")
        raise SystemExit(EXIT_USAGE)

    # ── Load policy ─────────────────────────────────────────────────────────
    policy_cfg: PolicyConfig
    policy_source = "defaults"
    if no_policy_file:
        policy_cfg = PolicyConfig()
        policy_source = "defaults (--no-policy-file)"
    elif policy_path:
        try:
            policy_cfg = load_policy(policy_path)
            policy_source = str(policy_path)
        except PromptGenieError as exc:
            diag_console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(EXIT_USAGE)
    else:
        discovered = discover_policy_file()
        if discovered:
            policy_cfg = load_policy(discovered)
            policy_source = str(discovered)
        else:
            policy_cfg = PolicyConfig()
            policy_source = "defaults (no policy file found)"

    # Apply inline overrides on top of discovered/loaded policy
    if max_risk is not None:
        policy_cfg.max_risk = max_risk.upper()
    if max_findings is not None:
        policy_cfg.max_findings = max_findings
    if min_score is not None:
        policy_cfg.min_score = min_score

    # ── Analyze prompt ──────────────────────────────────────────────────────
    result = analyze(
        prompt_text,
        file_path=file,
        scanner_config=pg_cfg.scanner,
        linter_config=pg_cfg.linter,
    )

    # ── Evaluate policy ─────────────────────────────────────────────────────
    evaluation = evaluate_policy(
        result,
        policy_cfg,
        provider=provider,
        classification=classification,
        explain=explain,
    )

    # ── Output ──────────────────────────────────────────────────────────────
    if output_format == "sarif":
        sarif = _policy_sarif(result, file_path=file, evaluation=evaluation,
                              policy_source=policy_source)
        sys.stdout.write(json.dumps(sarif, indent=2) + "\n")

    elif output_format == "json":
        scan_findings = [f for f in result.findings if f.source == "scan"]
        lint_findings = [f for f in result.findings if f.source == "lint"]
        qualifying_count = sum(
            1 for f in result.findings
            if f.source == "scan" and _risk_at_or_above(f.severity, policy_cfg.max_risk)
        )

        allowlist_warnings: list[str] = []
        for entry in pg_cfg.scanner.allowlist:
            if entry.is_expired():
                allowlist_warnings.append(
                    f"Allowlist entry '{entry.phrase}' expired on {entry.expires}"
                )

        data = {
            "schema_version": "1.0",
            "passed": evaluation.passed,
            "file": file,
            "policy_source": policy_source,
            "policy": {
                "max_risk": policy_cfg.max_risk,
                "max_findings": policy_cfg.max_findings,
                "min_score": policy_cfg.min_score,
                "allowed_providers": policy_cfg.allowed_providers,
            },
            "results": {
                "scan_risk_level": result.scan_risk,
                "qualifying_findings": qualifying_count,
                "lint_score": result.lint_score,
                "lint_issues": len(lint_findings),
            },
            "findings": [
                {
                    "code": f.code,
                    "category": f.category,
                    "risk": f.severity,
                    "confidence": f.confidence,
                    "line": f.location.line,
                    "message": f.title,
                    "recommendation": f.remediation,
                }
                for f in scan_findings
            ],
            "violations": [
                f"{v.rule}: {v.message}" for v in evaluation.violations
            ],
            "allowlist_warnings": allowlist_warnings,
            "warnings": evaluation.warnings,
            **({"explain": evaluation.explain_lines} if explain else {}),
        }
        sys.stdout.write(json.dumps(data, indent=2) + "\n")

    else:
        # Rich text output
        status = "[green]PASSED[/green]" if evaluation.passed else "[red]FAILED[/red]"
        icon = "✅" if evaluation.passed else "❌"
        console.print(
            f"\n{icon}  [bold]PromptGenie Policy — {status}[/bold]  "
            f"[dim]{file}[/dim]"
        )
        console.print(f"[dim]Policy: {policy_source}[/dim]")

        # Lint score line (shown when min_score is active)
        if min_score is not None and min_score > 0:
            score_color = "green" if result.lint_score >= min_score else "red"
            console.print(
                f"[dim]Lint score:[/dim] [{score_color}]{result.lint_score}/100[/{score_color}]"
                f" [dim](min: {min_score})[/dim]"
            )

        # Findings summary
        if result.findings:
            from rich.table import Table
            tbl = Table(show_header=True, header_style="bold", show_lines=False)
            tbl.add_column("Sev", width=7)
            tbl.add_column("Code", style="bold", no_wrap=True)
            tbl.add_column("Category")
            tbl.add_column("Finding")
            _sev_colors = {"CRITICAL": "bold red", "HIGH": "red",
                           "MEDIUM": "yellow", "LOW": "cyan", "INFO": "dim"}
            for f in sorted(result.findings,
                            key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2,
                                           "LOW": 3, "INFO": 4}.get(x.severity, 9)):
                color = _sev_colors.get(f.severity, "dim")
                tbl.add_row(
                    f"[{color}]{f.severity[:4]}[/{color}]",
                    f.code, f.category, f.title,
                )
            console.print(tbl)

        # Explain trace
        if explain and evaluation.explain_lines:
            console.print("\n[bold]Policy evaluation trace:[/bold]")
            for line in evaluation.explain_lines:
                color = "green" if "✓" in line else "red"
                console.print(f"  [{color}]{line}[/{color}]")

        # Violations
        if evaluation.violations:
            console.print("\n[bold red]Violations:[/bold red]")
            for v in evaluation.violations:
                detail = f"  [dim]{v.detail}[/dim]" if v.detail else ""
                console.print(f"  • [bold]{v.rule}[/bold]: {v.message}{detail}")
        else:
            console.print("\n[green]All policy thresholds met.[/green]")

        # Allowlist warnings
        for entry in pg_cfg.scanner.allowlist:
            if entry.is_expired():
                console.print(
                    f"[yellow]⚠[/yellow] Allowlist entry '{entry.phrase}' "
                    f"expired on {entry.expires} — suppression is inactive."
                )

        # Warnings
        for w in evaluation.warnings:
            console.print(f"[yellow]⚠[/yellow] {w}")

        console.print()

    raise SystemExit(EXIT_OK if evaluation.passed else EXIT_FAILURE)


# ---------------------------------------------------------------------------
# SARIF helper — two runs: one for scan findings, one for lint findings
# ---------------------------------------------------------------------------

_SARIF_LEVEL_MAP = {
    "CRITICAL": "error",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "note",
    "INFO": "none",
}

_SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


def _policy_sarif(result: object, *, file_path: str,
                  evaluation: object, policy_source: str) -> dict:
    """Build a SARIF 2.1.0 document with separate runs for scan and lint findings."""
    from promptgenie.core.analyze import AnalyzeResult

    ar: AnalyzeResult = result  # type: ignore[assignment]
    ev = evaluation  # type: ignore[assignment]

    def _run(driver_name: str, source_filter: str) -> dict:
        findings = [f for f in ar.findings if f.source == source_filter]
        seen: dict[str, dict] = {}
        results = []
        for f in findings:
            if f.code not in seen:
                seen[f.code] = {
                    "id": f.code,
                    "name": f.title[:80],
                    "shortDescription": {"text": f.title},
                    "fullDescription": {"text": f.remediation or f.title},
                }
            results.append({
                "ruleId": f.code,
                "level": _SARIF_LEVEL_MAP.get(f.severity, "note"),
                "message": {"text": f.title},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": file_path},
                        "region": {
                            "startLine": max(1, f.location.line or 1),
                            "startColumn": max(1, f.location.col or 1),
                        },
                    }
                }],
            })
        return {
            "tool": {"driver": {
                "name": driver_name,
                "version": "1.0.0",
                "rules": list(seen.values()),
            }},
            "results": results,
            "properties": {
                "policy_passed": ev.passed,
                "policy_source": policy_source,
                "violations": [{"rule": v.rule, "message": v.message}
                                for v in ev.violations],
            },
        }

    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            _run("promptgenie-scan", "scan"),
            _run("promptgenie-lint", "lint"),
        ],
    }
