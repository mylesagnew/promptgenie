"""policy.py — CI policy gate command.

Runs lint and scan on a prompt file and exits non-zero when findings violate
configured thresholds.  Designed to be dropped into a CI pipeline alongside
``scan`` and ``lint``:

    promptgenie policy my-prompt.md --max-risk HIGH --min-score 70

Exit codes:
    0  — prompt passes all policy thresholds
    1  — one or more thresholds exceeded (findings printed to stdout)
    2  — usage / configuration error
"""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.table import Table

from promptgenie.core.fileio import safe_read_text
from promptgenie.core.formatters import lint_to_sarif, scan_to_sarif
from promptgenie.core.linter import lint
from promptgenie.core.scanner import scan

_RISK_ORDER: dict[str, int] = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "NONE": 4,
}


def _risk_at_or_above(level: str, threshold: str) -> bool:
    """Return True if *level* is at least as severe as *threshold*."""
    return _RISK_ORDER.get(level, 99) <= _RISK_ORDER.get(threshold, 99)


@click.command("policy")
@click.argument("file", type=click.Path(exists=True, readable=True))
@click.option(
    "--max-risk",
    type=click.Choice(["CRITICAL", "HIGH", "MEDIUM", "LOW"], case_sensitive=False),
    default="HIGH",
    show_default=True,
    help="Fail if any security finding is at or above this risk level.",
)
@click.option(
    "--max-findings",
    type=int,
    default=0,
    show_default=True,
    help=(
        "Fail if the total number of qualifying security findings exceeds this count. "
        "0 = any qualifying finding fails (default)."
    ),
)
@click.option(
    "--min-score",
    type=int,
    default=0,
    show_default=True,
    help=(
        "Fail if the lint quality score is below this threshold. "
        "0 = lint score is not checked (default)."
    ),
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "sarif"]),
    default="text",
    show_default=True,
    help="Output format: text (Rich table), json (machine-readable), or sarif (SARIF v2.1.0).",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    help="Path to .promptgenie.yaml config file.",
)
@click.option(
    "--no-config",
    is_flag=True,
    default=False,
    help="Ignore any .promptgenie.yaml config file.",
)
def policy(
    file: str,
    max_risk: str,
    max_findings: int,
    min_score: int,
    output_format: str,
    config_path: str | None,
    no_config: bool,
) -> None:
    """CI policy gate — exit 1 if the prompt violates configured thresholds.

    FILE is the prompt file to evaluate.

    Runs both lint and scan and exits 1 if any threshold is breached:

    \b
      --max-risk    : any security finding at or above this level → fail
      --max-findings: total qualifying findings exceed this count → fail
      --min-score   : lint quality score below this value → fail

    All thresholds default to "any HIGH finding fails; lint score unchecked".
    """
    from promptgenie.core.config import PromptGenieConfig, load_config

    cfg: PromptGenieConfig
    if no_config:
        cfg = PromptGenieConfig()
    else:
        try:
            cfg = load_config(config_path)
        except (FileNotFoundError, ValueError) as exc:
            if config_path:
                click.echo(f"error: cannot load config {config_path!r}: {exc}", err=True)
                sys.exit(2)
            cfg = PromptGenieConfig()

    # ── Read prompt ────────────────────────────────────────────────────────────
    try:
        prompt_text = safe_read_text(file)
    except (OSError, ValueError) as exc:
        click.echo(f"error: cannot read {file!r}: {exc}", err=True)
        sys.exit(2)

    # ── Run lint + scan ────────────────────────────────────────────────────────
    lint_result = lint(prompt_text, config=cfg.linter if cfg else None)
    scan_result = scan(prompt_text, config=cfg.scanner if cfg else None)

    # ── Evaluate thresholds ────────────────────────────────────────────────────
    qualifying_findings = [f for f in scan_result.findings if _risk_at_or_above(f.risk, max_risk)]

    violations: list[str] = []

    if qualifying_findings and (max_findings == 0 or len(qualifying_findings) > max_findings):
        violations.append(
            f"{len(qualifying_findings)} finding(s) at or above {max_risk} risk "
            f"(threshold: {'any' if max_findings == 0 else max_findings})"
        )

    if min_score > 0 and lint_result.score < min_score:
        violations.append(f"lint score {lint_result.score}/100 is below minimum {min_score}")

    # ── Warn on expired / malformed allowlist entries ─────────────────────────
    allowlist_warnings: list[str] = []
    if cfg and cfg.scanner.allowlist:
        for entry in cfg.scanner.allowlist:
            if entry.expires and entry.is_expired():
                allowlist_warnings.append(
                    f"Allowlist entry for phrase {entry.phrase!r} "
                    f"(expires: {entry.expires or 'malformed'}) is expired or malformed — "
                    "suppression is inactive."
                )

    passed = len(violations) == 0

    # ── Output ────────────────────────────────────────────────────────────────
    if output_format == "sarif":
        # Emit a combined SARIF document with both lint and scan results.
        # SARIF does not natively model policy-pass/fail, so we include both
        # run objects and let the CI system interpret the findings count.
        import json as _json

        lint_sarif = _json.loads(lint_to_sarif(lint_result, file))
        scan_sarif = _json.loads(scan_to_sarif(scan_result, file))
        combined = lint_sarif.copy()
        combined["runs"] = lint_sarif["runs"] + scan_sarif["runs"]
        click.echo(_json.dumps(combined, indent=2))
    elif output_format == "json":
        out = {
            "passed": passed,
            "file": file,
            "policy": {
                "max_risk": max_risk,
                "max_findings": max_findings,
                "min_score": min_score,
            },
            "results": {
                "scan_risk_level": scan_result.risk_level,
                "qualifying_findings": len(qualifying_findings),
                "lint_score": lint_result.score,
                "lint_issues": len(lint_result.issues),
            },
            "violations": violations,
            "allowlist_warnings": allowlist_warnings,
            "findings": [
                {
                    "code": f.code,
                    "category": f.category,
                    "risk": f.risk,
                    "confidence": f.confidence,
                    "line": f.line,
                    "message": f.message,
                    "recommendation": f.recommendation,
                }
                for f in qualifying_findings
            ],
        }
        click.echo(json.dumps(out, indent=2))
    else:
        console = Console()
        status_icon = "✅" if passed else "❌"
        console.print(
            f"\n{status_icon}  PromptGenie Policy — [bold]{'PASSED' if passed else 'FAILED'}[/bold]"
            f"  [dim]{file}[/dim]\n"
        )

        if qualifying_findings:
            table = Table(title=f"Security Findings (≥ {max_risk})", show_lines=False)
            table.add_column("Code", style="bold red")
            table.add_column("Risk")
            table.add_column("Line", justify="right")
            table.add_column("Message")
            for f in qualifying_findings:
                table.add_row(f.code, f.risk, str(f.line), f.message)
            console.print(table)

        if min_score > 0:
            score_colour = "green" if lint_result.score >= min_score else "red"
            console.print(
                f"Lint score: [{score_colour}]{lint_result.score}/100[/{score_colour}]"
                f"  (minimum: {min_score})"
            )

        for warning in allowlist_warnings:
            console.print(f"[yellow]⚠ Allowlist:[/yellow] {warning}")

        if violations:
            console.print("\n[bold red]Violations:[/bold red]")
            for v in violations:
                console.print(f"  • {v}")
        else:
            console.print("[green]All policy thresholds met.[/green]")

        console.print()

    sys.exit(0 if passed else 1)
