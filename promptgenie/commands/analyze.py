"""analyze.py — ``promptgenie analyze`` command.

Aggregate lint + scan + policy gate in one pass with a unified finding model.

Examples
--------
  promptgenie analyze prompt.md
  promptgenie analyze prompt.md --format json | jq '.findings[] | select(.severity=="HIGH")'
  promptgenie analyze prompt.md --format sarif | gh sarif upload -
  promptgenie analyze prompt.md --categories secret-exposure,prompt-injection
  cat prompt.md | promptgenie analyze -
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from promptgenie.core.analyze import analyze, findings_to_sarif
from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE, PromptGenieError
from promptgenie.core.fileio import safe_read_text
from promptgenie.renderers.rich import console, diag_console, is_structured_mode

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
_SEVERITY_COLORS = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "cyan",
    "INFO": "dim",
}
_CATEGORY_LABELS = {
    "prompt-injection": "Prompt Injection",
    "data-leakage": "Data Leakage",
    "secret-exposure": "Secret Exposure",
    "unsafe-agent-permission": "Unsafe Agent Permission",
    "destructive-action": "Destructive Action",
    "compliance": "Compliance",
    "quality": "Quality",
}


@click.command("analyze")
@click.argument("file", default="-", metavar="FILE|-")
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json", "yaml", "sarif"], case_sensitive=False),
              default="rich", show_default=True,
              help="Output format.")
@click.option("--categories", default=None, metavar="CAT[,CAT...]",
              help="Comma-separated categories to include. Default: all.")
@click.option("--min-severity",
              type=click.Choice(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"],
                                case_sensitive=False),
              default="LOW", show_default=True,
              help="Only report findings at or above this severity.")
@click.option("--no-lint", is_flag=True, help="Skip lint analysis.")
@click.option("--no-scan", is_flag=True, help="Skip security scan.")
@click.option("--fail-on",
              type=click.Choice(["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"],
                                case_sensitive=False),
              default="HIGH", show_default=True,
              help="Exit 1 if any finding at or above this severity is found. "
                   "Use NONE to always exit 0.")
@click.option("--config", "config_path", default=None,
              help="Path to .promptgenie.yaml config file.")
@click.option("--custom-rules", "custom_rules_file", default=None, type=click.Path(exists=True),
              help="YAML file with extra scan rules to run alongside built-in rules.")
def analyze_cmd(
    file: str,
    output_format: str,
    categories: str | None,
    min_severity: str,
    no_lint: bool,
    no_scan: bool,
    fail_on: str,
    config_path: str | None,
    custom_rules_file: str | None,
) -> None:
    """Analyze a prompt for security issues, PII, injection risks, and quality problems.

    Runs lint + scan in a single pass and produces a unified finding report.
    Uses a severity-aware exit code suitable for CI/CD policy gates.

    \b
    Examples:
      promptgenie analyze prompt.md
      promptgenie analyze prompt.md --format json | jq '.findings'
      promptgenie analyze prompt.md --format sarif | gh sarif upload -
      promptgenie analyze prompt.md --fail-on CRITICAL
      promptgenie analyze prompt.md --min-severity HIGH --no-lint
      promptgenie analyze prompt.md --custom-rules my-rules.yaml
      cat prompt.md | promptgenie analyze -
    """
    try:
        text = safe_read_text(file)
    except (OSError, ValueError) as exc:
        diag_console.print(f"[red]Error:[/red] Cannot read {file!r}: {exc}")
        raise SystemExit(EXIT_USAGE)

    cfg: PromptGenieConfig
    try:
        cfg = load_config(config_path)
    except Exception:
        cfg = PromptGenieConfig()

    # Load custom scan rules if provided
    if custom_rules_file and not no_scan:
        import yaml as _yaml
        from promptgenie.core.scanner import ScanRule
        try:
            raw_rules = _yaml.safe_load(
                Path(custom_rules_file).read_text(encoding="utf-8")
            ) or {}
            extra_rules = []
            for r in raw_rules.get("rules", []):
                extra_rules.append(ScanRule(
                    id=str(r.get("id", "CUSTOM")),
                    category=str(r.get("category", "custom")),
                    pattern=str(r.get("pattern", "")),
                    risk=str(r.get("risk", "MEDIUM")),
                    confidence=str(r.get("confidence", "MEDIUM")),
                    message=str(r.get("message", "Custom rule match.")),
                    recommendation=str(r.get("recommendation", "")),
                    use_original_text=bool(r.get("use_original_text", False)),
                ))
            cfg.scanner.custom_scan_rules.extend(extra_rules)
        except Exception as exc:
            diag_console.print(f"[yellow]Warning:[/yellow] Could not load custom rules: {exc}")

    result = analyze(
        text,
        file_path=file,
        scanner_config=cfg.scanner if not no_scan else None,
        linter_config=cfg.linter if not no_lint else None,
        include_scan=not no_scan,
        include_lint=not no_lint,
    )

    # Filter by severity
    min_order = _SEVERITY_ORDER.get(min_severity.upper(), 4)
    findings = [
        f for f in result.findings
        if _SEVERITY_ORDER.get(f.severity, 99) <= min_order
    ]

    # Filter by category
    if categories:
        allowed_cats = {c.strip().lower() for c in categories.split(",")}
        findings = [f for f in findings if f.category in allowed_cats]

    # Sort by severity then code
    findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 99), f.code))

    # ── Output ──────────────────────────────────────────────────────────────
    if output_format == "sarif":
        from promptgenie.core.analyze import AnalyzeResult
        filtered_result = AnalyzeResult(
            findings=findings,
            lint_score=result.lint_score,
            scan_risk=result.scan_risk,
        )
        sarif_doc = findings_to_sarif(filtered_result, file_path=file)
        sys.stdout.write(json.dumps(sarif_doc, indent=2) + "\n")
    elif is_structured_mode(output_format):
        data = {
            "schema_version": "1.0",
            "file": file,
            "summary": {
                "total": len(findings),
                "by_severity": result.severity_counts,
                "overall_risk": result.overall_risk,
                "lint_score": result.lint_score,
            },
            "findings": [
                {
                    "code": f.code,
                    "title": f.title,
                    "severity": f.severity,
                    "category": f.category,
                    "location": {
                        "file": f.location.file,
                        "line": f.location.line,
                        "col": f.location.col,
                    },
                    "evidence": f.evidence,
                    "remediation": f.remediation,
                    "confidence": f.confidence,
                    "source": f.source,
                    "tags": f.tags,
                }
                for f in findings
            ],
        }
        if output_format == "yaml":
            sys.stdout.write(yaml.dump(data, default_flow_style=False, sort_keys=False))
        else:
            sys.stdout.write(json.dumps(data, indent=2) + "\n")
    else:
        _print_rich(findings, result, file, fail_on)

    # ── Exit code ────────────────────────────────────────────────────────────
    if fail_on.upper() == "NONE":
        raise SystemExit(EXIT_OK)

    fail_order = _SEVERITY_ORDER.get(fail_on.upper(), 99)
    has_failure = any(
        _SEVERITY_ORDER.get(f.severity, 99) <= fail_order for f in findings
    )
    raise SystemExit(EXIT_FAILURE if has_failure else EXIT_OK)


def _print_rich(findings: list, result: object, file: str, fail_on: str) -> None:
    from rich.table import Table

    counts = result.severity_counts  # type: ignore[attr-defined]
    score = result.lint_score  # type: ignore[attr-defined]
    risk = result.overall_risk  # type: ignore[attr-defined]

    risk_color = _SEVERITY_COLORS.get(risk, "dim")
    console.print(
        f"\n[bold]PromptGenie Analyze[/bold]  [dim]{file}[/dim]  "
        f"Risk: [{risk_color}]{risk}[/{risk_color}]  "
        f"Lint: {score}/100"
    )

    if not findings:
        console.print("[green]✓ No findings.[/green]\n")
        return

    table = Table(show_header=True, header_style="bold", show_lines=False)
    table.add_column("Sev", width=8)
    table.add_column("Code", style="bold", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    table.add_column("Line", justify="right", width=5)
    table.add_column("Finding")
    table.add_column("Source", width=6)

    for f in findings:
        color = _SEVERITY_COLORS.get(f.severity, "dim")
        cat_label = _CATEGORY_LABELS.get(f.category, f.category)
        table.add_row(
            f"[{color}]{f.severity[:4]}[/{color}]",
            f.code,
            cat_label,
            str(f.location.line) if f.location.line else "—",
            f.title,
            f.source,
        )

    console.print(table)

    # Summary line
    parts = []
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        n = counts.get(sev, 0)
        if n:
            color = _SEVERITY_COLORS[sev]
            parts.append(f"[{color}]{n} {sev}[/{color}]")
    if parts:
        console.print("  " + "  ".join(parts))
    console.print()
