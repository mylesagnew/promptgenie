"""gh_reporter.py — GitHub Actions native reporter.

Detects the GITHUB_ACTIONS environment variable and, when set, emits:
  - ::error / ::warning workflow commands for annotation on changed files
  - A Markdown step summary written to $GITHUB_STEP_SUMMARY
  - SARIF-compatible JSON for gh sarif upload

Usage
-----
  from promptgenie.core.gh_reporter import GHReporter
  reporter = GHReporter()
  if reporter.active:
      reporter.annotate_findings(findings, file_path="prompts/auth.md")
      reporter.write_step_summary(summary_md)

Public API
----------
  ``GHReporter``             — main class, auto-detects GITHUB_ACTIONS
  ``is_github_actions()``    → bool
  ``format_step_summary(...)`` → str  (Markdown)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def is_github_actions() -> bool:
    """Return True when running inside a GitHub Actions workflow."""
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def _confine_to_runner_temp(path: str) -> str | None:
    """Canonicalise *path* and confine it to the GitHub runner temp area.

    ``GITHUB_STEP_SUMMARY`` is read from the environment and is therefore
    attacker-influenceable inside a workflow. Before appending to it we resolve
    the path (following ``..`` and symlinks) and require the result to live
    inside ``$RUNNER_TEMP`` — the directory GitHub uses for file-command files
    such as the step summary. Anything that escapes that root, or a missing
    ``RUNNER_TEMP``, yields ``None`` so the caller refuses to write (CWE-23).
    """
    runner_temp = os.environ.get("RUNNER_TEMP")
    if not runner_temp:
        return None
    try:
        resolved = Path(path).resolve()
        root = Path(runner_temp).resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return str(resolved)


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------


def _escape_annotation(value: str) -> str:
    """Escape special chars for a GHA workflow command value."""
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _annotation(level: str, message: str, *, file: str = "", line: int = 0, col: int = 0) -> str:
    """Format a single ::error/::warning/::notice annotation line."""
    params: list[str] = []
    if file:
        params.append(f"file={_escape_annotation(file)}")
    if line:
        params.append(f"line={line}")
    if col:
        params.append(f"col={col}")
    param_str = ",".join(params)
    prefix = f"::{level} {param_str}::" if param_str else f"::{level}::"
    return prefix + _escape_annotation(message)


class GHReporter:
    """Emits GitHub Actions annotations and step summary."""

    def __init__(self, *, out: Any = None, summary_path: str | None = None) -> None:
        self._out = out or sys.stderr
        self._summary_path = summary_path or os.environ.get("GITHUB_STEP_SUMMARY")
        self.active = is_github_actions()

    # ── Annotations ──────────────────────────────────────────────────────────

    def error(self, message: str, *, file: str = "", line: int = 0, col: int = 0) -> None:
        print(_annotation("error", message, file=file, line=line, col=col), file=self._out)

    def warning(self, message: str, *, file: str = "", line: int = 0, col: int = 0) -> None:
        print(_annotation("warning", message, file=file, line=line, col=col), file=self._out)

    def notice(self, message: str, *, file: str = "", line: int = 0, col: int = 0) -> None:
        print(_annotation("notice", message, file=file, line=line, col=col), file=self._out)

    def annotate_findings(self, findings: list, *, file_path: str = "") -> None:
        """Emit one ::error or ::warning annotation per finding."""
        _SEVERITY_LEVEL = {
            "CRITICAL": "error",
            "HIGH": "error",
            "MEDIUM": "warning",
            "LOW": "notice",
            "INFO": "notice",
        }
        for f in findings:
            level = _SEVERITY_LEVEL.get(getattr(f, "severity", "MEDIUM"), "warning")
            line = getattr(getattr(f, "location", None), "line", 0) or 0
            col = getattr(getattr(f, "location", None), "col", 0) or 0
            msg = f"[{getattr(f, 'code', '?')}] {getattr(f, 'title', str(f))}"
            fn = file_path or getattr(getattr(f, "location", None), "file", "")
            getattr(self, level)(msg, file=fn, line=line, col=col)

    def annotate_regression(self, regression: Any, *, file_path: str = "") -> None:
        """Emit a ::error annotation for a baseline regression."""
        self.error(
            f"[REGRESSION:{regression.metric}] {regression.message}",
            file=file_path,
        )

    def annotate_eval_failures(self, case_results: list, *, file_path: str = "") -> None:
        """Emit ::error annotations for failed eval cases."""
        for case in case_results:
            if not getattr(case, "passed", True) and not getattr(case, "skipped", False):
                failures = getattr(case, "failure_messages", [])
                for msg in failures:
                    self.error(f"[EVAL:{case.case_name}] {msg}", file=file_path)

    # ── Step summary ─────────────────────────────────────────────────────────

    def write_step_summary(self, markdown: str) -> None:
        """Append *markdown* to the GITHUB_STEP_SUMMARY file.

        When running inside a GitHub Actions workflow the destination is
        canonicalised and confined to ``$RUNNER_TEMP`` first; a path that
        escapes that area is refused rather than written (CWE-23 path
        traversal). Outside a workflow the configured path is used as-is.
        """
        if not self._summary_path:
            return

        target = self._summary_path
        if is_github_actions():
            confined = _confine_to_runner_temp(self._summary_path)
            if confined is None:
                return  # outside the trusted runner temp area — refuse to write
            target = confined

        try:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(markdown)
                if not markdown.endswith("\n"):
                    fh.write("\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Step summary formatters
# ---------------------------------------------------------------------------


def format_analyze_summary(
    findings: list,
    file_path: str,
    *,
    overall_risk: str = "NONE",
    lint_score: int = 100,
    passed: bool = True,
) -> str:
    """Return Markdown step summary for promptgenie analyze."""
    status = "✅ Passed" if passed else "❌ Failed"
    lines = [
        f"## PromptGenie Analyze — {status}",
        "",
        "| File | Risk | Lint Score | Findings |",
        "|------|------|-----------|----------|",
        f"| `{file_path}` | **{overall_risk}** | {lint_score}/100 | {len(findings)} |",
        "",
    ]
    if findings:
        lines += [
            "### Top Findings",
            "",
            "| Severity | Code | Title |",
            "|----------|------|-------|",
        ]
        for f in findings[:10]:
            sev = getattr(f, "severity", "?")
            code = getattr(f, "code", "?")
            title = getattr(f, "title", str(f))
            lines.append(f"| {sev} | `{code}` | {title} |")
        if len(findings) > 10:
            lines.append(f"\n*…and {len(findings) - 10} more findings.*")
        lines.append("")
    return "\n".join(lines)


def format_eval_summary(
    suite_result: Any,
    *,
    regression_report: Any = None,
    prompt_file: str = "",
) -> str:
    """Return Markdown step summary for promptgenie eval run."""
    status = "✅ Passed" if suite_result.passed else "❌ Failed"
    lines = [
        f"## PromptGenie Eval — {status}",
        "",
        f"**Suite:** {suite_result.suite_name}",
        (f"**Prompt:** `{prompt_file}`" if prompt_file else ""),
        "",
        "| Total | Passed | Failed | Skipped |",
        "|-------|--------|--------|---------|",
        f"| {suite_result.total} | {suite_result.pass_count} | "
        f"{suite_result.fail_count} | {suite_result.skip_count} |",
        "",
    ]
    # Failures table
    failed = [c for c in suite_result.cases if not c.passed and not c.skipped]
    if failed:
        lines += ["### Failed Cases", "", "| Case | Failure |", "|------|---------|"]
        for c in failed:
            msgs = "; ".join(c.failure_messages[:2]) or (c.error or "unknown")
            lines.append(f"| {c.case_name} | {msgs} |")
        lines.append("")
    # Regression block
    if regression_report and regression_report.has_regressions:
        lines += ["### ⚠️ Baseline Regressions", ""]
        for r in regression_report.regressions:
            lines.append(f"- **{r.model}** `{r.metric}`: {r.message}")
        lines.append("")
    return "\n".join(ln for ln in lines if ln is not None)


def format_matrix_summary(
    matrix_result: Any,
    *,
    regression_report: Any = None,
    prompt_file: str = "",
) -> str:
    """Return Markdown step summary for promptgenie evaluate (matrix)."""
    all_ok = all(r.ok for r in matrix_result.results)
    status = "✅ All models OK" if all_ok else "⚠️ Some models failed"
    lines = [
        f"## PromptGenie Evaluate — {status}",
        "",
        (f"**Prompt:** `{prompt_file}`" if prompt_file else ""),
        "",
        "| Model | Latency | Tokens | Cost | Rubric | Safety |",
        "|-------|---------|--------|------|--------|--------|",
    ]
    for r in matrix_result.results:
        m = r.metrics
        if r.ok:
            lines.append(
                f"| {r.display_name} | {m.latency_ms:.0f}ms | {m.total_tokens} | "
                f"${m.cost_usd:.4f} | {m.rubric_score or '—'} | {m.safety_score or '—'} |"
            )
        else:
            lines.append(f"| {r.display_name} | ❌ {r.error} | — | — | — | — |")
    lines.append("")
    if regression_report and regression_report.has_regressions:
        lines += ["### ⚠️ Baseline Regressions", ""]
        for reg in regression_report.regressions:
            lines.append(f"- **{reg.model}** `{reg.metric}`: {reg.message}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SARIF helpers for CI upload
# ---------------------------------------------------------------------------


def eval_results_to_sarif(suite_result: Any, *, file_path: str = "") -> dict:
    """Convert an EvalSuiteResult to a minimal SARIF 2.1.0 document."""
    rules = []
    results = []
    for case in suite_result.cases:
        if case.skipped or case.passed:
            continue
        rule_id = f"EVAL_{case.case_name.upper().replace(' ', '_')}"
        rules.append(
            {
                "id": rule_id,
                "shortDescription": {"text": f"Eval case failed: {case.case_name}"},
            }
        )
        for ar in case.assertion_results:
            if not ar.passed:
                loc: dict = {}
                if file_path:
                    loc = {"physicalLocation": {"artifactLocation": {"uri": file_path}}}
                results.append(
                    {
                        "ruleId": rule_id,
                        "level": "error",
                        "message": {"text": ar.message},
                        "locations": [loc] if loc else [],
                    }
                )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "PromptGenie Eval",
                        "version": "1.0",
                        "rules": rules,
                    }
                },
                "results": results,
                "properties": {
                    "suite_name": suite_result.suite_name,
                    "passed": suite_result.passed,
                    "total": suite_result.total,
                },
            }
        ],
    }
