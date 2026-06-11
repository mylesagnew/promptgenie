"""differ.py — prompt diff engine for PromptGenie.

Core function: ``diff_prompts(a_path, b_path)`` → ``DiffResult``

Output formatters
-----------------
``diff_to_json(result)``      → JSON string (schema_version: "1.0")
``diff_to_markdown(result)``  → GitHub-flavoured Markdown table summary
``diff_to_yaml(result)``      → YAML string (mirrors JSON structure)
``build_side_by_side(result)`` → list of (a_line, b_line, status) triples
                                 for Rich table rendering in the command layer
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

from promptgenie.core.fileio import safe_read_text
from promptgenie.core.generator import estimate_tokens, score_prompt
from promptgenie.core.linter import LintResult, lint
from promptgenie.core.scanner import ScanResult, scan

if TYPE_CHECKING:
    from promptgenie.core.config import PromptGenieConfig

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SectionDelta:
    name: str
    status: str  # "added" | "removed" | "changed" | "unchanged"
    a_lines: list[str] = field(default_factory=list)
    b_lines: list[str] = field(default_factory=list)


@dataclass
class DiffResult:
    # Raw text
    a_text: str
    b_text: str
    a_path: str
    b_path: str

    # Token delta
    a_tokens: int
    b_tokens: int

    # Quality scores
    a_score: dict
    b_score: dict

    # Lint
    a_lint: LintResult
    b_lint: LintResult

    # Security
    a_scan: ScanResult
    b_scan: ScanResult

    # Line-level diff
    unified_diff: list[str] = field(default_factory=list)

    # Section-level changes
    section_deltas: list[SectionDelta] = field(default_factory=list)

    @property
    def token_delta(self) -> int:
        return self.b_tokens - self.a_tokens

    @property
    def score_delta(self) -> int:
        return int(self.b_score["total"]) - int(self.a_score["total"])

    @property
    def lint_delta(self) -> int:
        return len(self.b_lint.issues) - len(self.a_lint.issues)

    @property
    def new_lint_issues(self) -> list:
        a_codes = {i.code for i in self.a_lint.issues}
        return [i for i in self.b_lint.issues if i.code not in a_codes]

    @property
    def resolved_lint_issues(self) -> list:
        b_codes = {i.code for i in self.b_lint.issues}
        return [i for i in self.a_lint.issues if i.code not in b_codes]

    @property
    def new_security_findings(self) -> list:
        a_codes = {f.code for f in self.a_scan.findings}
        return [f for f in self.b_scan.findings if f.code not in a_codes]

    @property
    def resolved_security_findings(self) -> list:
        b_codes = {f.code for f in self.b_scan.findings}
        return [f for f in self.a_scan.findings if f.code not in b_codes]


# ---------------------------------------------------------------------------
# Section extraction and delta helpers
# ---------------------------------------------------------------------------


def _extract_sections(text: str) -> dict[str, list[str]]:
    """Split a prompt into sections keyed by markdown heading."""
    sections: dict[str, list[str]] = {}
    current = "__preamble__"
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if lines:
                sections[current] = lines
            current = line[3:].strip()
            lines = []
        else:
            lines.append(line)
    if lines:
        sections[current] = lines
    return sections


def _section_deltas(a_text: str, b_text: str) -> list[SectionDelta]:
    a_sections = _extract_sections(a_text)
    b_sections = _extract_sections(b_text)
    all_keys = list(dict.fromkeys(list(a_sections) + list(b_sections)))
    deltas = []
    for key in all_keys:
        a_lines = a_sections.get(key, [])
        b_lines = b_sections.get(key, [])
        if key not in a_sections:
            status = "added"
        elif key not in b_sections:
            status = "removed"
        elif a_lines == b_lines:
            status = "unchanged"
        else:
            status = "changed"
        deltas.append(SectionDelta(name=key, status=status, a_lines=a_lines, b_lines=b_lines))
    return deltas


# ---------------------------------------------------------------------------
# Side-by-side builder
# ---------------------------------------------------------------------------


@dataclass
class SideBySideRow:
    """One row of a side-by-side diff table."""

    a_line: str
    b_line: str
    status: str  # "equal" | "replace" | "insert" | "delete" | "header"


def build_side_by_side(result: DiffResult) -> list[SideBySideRow]:
    """Build a list of side-by-side rows from a ``DiffResult``.

    Each ``SectionDelta`` becomes a header row followed by the line-level
    diff of that section's content.  Unchanged sections are shown collapsed
    (only the header).  Changed sections show all lines with diff status.
    """
    rows: list[SideBySideRow] = []

    for delta in result.section_deltas:
        if delta.name == "__preamble__" and not delta.a_lines and not delta.b_lines:
            continue

        display_name = delta.name if delta.name != "__preamble__" else "(preamble)"
        rows.append(
            SideBySideRow(
                a_line=f"## {display_name}" if delta.name != "__preamble__" else "(preamble)",
                b_line=f"## {display_name}" if delta.name != "__preamble__" else "(preamble)",
                status=f"header:{delta.status}",
            )
        )

        if delta.status == "unchanged":
            # Show first 3 lines of unchanged content collapsed
            for line in delta.a_lines[:3]:
                rows.append(SideBySideRow(a_line=line, b_line=line, status="equal"))
            if len(delta.a_lines) > 3:
                rows.append(
                    SideBySideRow(
                        a_line=f"  … {len(delta.a_lines) - 3} more lines",
                        b_line=f"  … {len(delta.b_lines) - 3} more lines",
                        status="equal",
                    )
                )
        elif delta.status == "added":
            for line in delta.b_lines:
                rows.append(SideBySideRow(a_line="", b_line=line, status="insert"))
        elif delta.status == "removed":
            for line in delta.a_lines:
                rows.append(SideBySideRow(a_line=line, b_line="", status="delete"))
        else:
            # "changed" — use SequenceMatcher for line-level pairing
            matcher = difflib.SequenceMatcher(None, delta.a_lines, delta.b_lines)
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal":
                    for a, b in zip(delta.a_lines[i1:i2], delta.b_lines[j1:j2]):
                        rows.append(SideBySideRow(a_line=a, b_line=b, status="equal"))
                elif tag == "replace":
                    a_chunk = delta.a_lines[i1:i2]
                    b_chunk = delta.b_lines[j1:j2]
                    for a, b in zip(a_chunk, b_chunk):
                        rows.append(SideBySideRow(a_line=a, b_line=b, status="replace"))
                    for extra in a_chunk[len(b_chunk) :]:
                        rows.append(SideBySideRow(a_line=extra, b_line="", status="delete"))
                    for extra in b_chunk[len(a_chunk) :]:
                        rows.append(SideBySideRow(a_line="", b_line=extra, status="insert"))
                elif tag == "insert":
                    for b in delta.b_lines[j1:j2]:
                        rows.append(SideBySideRow(a_line="", b_line=b, status="insert"))
                elif tag == "delete":
                    for a in delta.a_lines[i1:i2]:
                        rows.append(SideBySideRow(a_line=a, b_line="", status="delete"))

    return rows


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _diff_to_dict(result: DiffResult) -> dict:
    """Shared data structure used by JSON and YAML serialisers."""
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "promptgenie",
        "command": "diff",
        "a": result.a_path,
        "b": result.b_path,
        "summary": {
            "tokens": {"a": result.a_tokens, "b": result.b_tokens, "delta": result.token_delta},
            "score": {
                "a": result.a_score["total"],
                "b": result.b_score["total"],
                "delta": result.score_delta,
            },
            "lint_issues": {
                "a": len(result.a_lint.issues),
                "b": len(result.b_lint.issues),
                "delta": result.lint_delta,
            },
            "security_findings": {
                "a": len(result.a_scan.findings),
                "b": len(result.b_scan.findings),
                "delta": len(result.b_scan.findings) - len(result.a_scan.findings),
            },
        },
        "score_breakdown": {
            dim: {
                "a": result.a_score["breakdown"].get(dim, 0),
                "b": result.b_score["breakdown"].get(dim, 0),
                "delta": result.b_score["breakdown"].get(dim, 0)
                - result.a_score["breakdown"].get(dim, 0),
            }
            for dim in result.a_score.get("breakdown", {})
        },
        "sections": [
            {
                "name": d.name,
                "status": d.status,
            }
            for d in result.section_deltas
            if d.name != "__preamble__"
        ],
        "new_lint_issues": [
            {"code": i.code, "severity": i.severity, "message": i.message}
            for i in result.new_lint_issues
        ],
        "resolved_lint_issues": [
            {"code": i.code, "severity": i.severity, "message": i.message}
            for i in result.resolved_lint_issues
        ],
        "new_security_findings": [
            {"code": f.code, "risk": f.risk, "message": f.message}
            for f in result.new_security_findings
        ],
        "resolved_security_findings": [
            {"code": f.code, "risk": f.risk, "message": f.message}
            for f in result.resolved_security_findings
        ],
    }


def diff_to_json(result: DiffResult) -> str:
    """Serialise *result* as a JSON string."""
    return json.dumps(_diff_to_dict(result), indent=2)


def diff_to_yaml(result: DiffResult) -> str:
    """Serialise *result* as a YAML string."""
    return yaml.dump(_diff_to_dict(result), sort_keys=False, allow_unicode=True)


def diff_to_markdown(result: DiffResult) -> str:
    """Serialise *result* as a GitHub-flavoured Markdown summary."""
    a, b = result.a_path, result.b_path

    def _sign(n: int, invert: bool = False) -> str:
        if n == 0:
            return "—"
        if (n > 0 and not invert) or (n < 0 and invert):
            return f"🟢 +{n}" if n > 0 else f"🟢 {n}"
        return f"🔴 +{n}" if n > 0 else f"🔴 {n}"

    lines = [
        f"## Diff: `{a}` → `{b}`",
        "",
        "### Summary",
        "",
        "| Metric | A | B | Delta |",
        "|--------|---|---|-------|",
        f"| Tokens | {result.a_tokens} | {result.b_tokens} | {_sign(result.token_delta, invert=True)} |",
        f"| Quality score | {result.a_score['total']}/100 | {result.b_score['total']}/100 | {_sign(result.score_delta)} |",
        f"| Lint issues | {len(result.a_lint.issues)} | {len(result.b_lint.issues)} | {_sign(result.lint_delta, invert=True)} |",
        f"| Security findings | {len(result.a_scan.findings)} | {len(result.b_scan.findings)} | {_sign(len(result.b_scan.findings) - len(result.a_scan.findings), invert=True)} |",
        "",
    ]

    # Section changes
    changed_sections = [d for d in result.section_deltas if d.status != "unchanged" and d.name != "__preamble__"]
    if changed_sections:
        lines += ["### Section Changes", ""]
        status_emoji = {"added": "🟢 ADDED", "removed": "🔴 REMOVED", "changed": "🟡 CHANGED"}
        for d in changed_sections:
            lines.append(f"- **{d.name}** — {status_emoji.get(d.status, d.status)}")
        lines.append("")

    # New lint issues
    if result.new_lint_issues:
        lines += ["### New Lint Issues", ""]
        for i in result.new_lint_issues:
            lines.append(f"- `{i.code}` **{i.severity}** — {i.message}")
        lines.append("")

    # Resolved lint issues
    if result.resolved_lint_issues:
        lines += ["### Resolved Lint Issues", ""]
        for i in result.resolved_lint_issues:
            lines.append(f"- ~~`{i.code}`~~ {i.message}")
        lines.append("")

    # Security changes
    if result.new_security_findings:
        lines += ["### New Security Findings", ""]
        for f in result.new_security_findings:
            lines.append(f"- `{f.code}` **{f.risk}** — {f.message}")
        lines.append("")

    if result.resolved_security_findings:
        lines += ["### Resolved Security Findings", ""]
        for f in result.resolved_security_findings:
            lines.append(f"- ~~`{f.code}`~~ {f.message}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def diff_prompts(
    a_path: str,
    b_path: str,
    target: str = "claude",
    config: "PromptGenieConfig | None" = None,
) -> DiffResult:
    a_text = safe_read_text(a_path)
    b_text = safe_read_text(b_path)

    # Load profile for scoring (best-effort)
    try:
        from promptgenie.core.generator import load_profile

        profile = load_profile(target)
    except Exception:
        profile = {"name": target, "required_sections": [], "forbidden_patterns": []}

    a_tokens = estimate_tokens(a_text)
    b_tokens = estimate_tokens(b_text)

    a_score = score_prompt(a_text, profile)
    b_score = score_prompt(b_text, profile)

    linter_cfg = config.linter if config is not None else None
    scanner_cfg = config.scanner if config is not None else None

    a_lint = lint(a_text, config=linter_cfg)
    b_lint = lint(b_text, config=linter_cfg)

    a_scan = scan(a_text, config=scanner_cfg)
    b_scan = scan(b_text, config=scanner_cfg)

    unified = list(
        difflib.unified_diff(
            a_text.splitlines(keepends=True),
            b_text.splitlines(keepends=True),
            fromfile=a_path,
            tofile=b_path,
            lineterm="",
        )
    )

    deltas = _section_deltas(a_text, b_text)

    return DiffResult(
        a_text=a_text,
        b_text=b_text,
        a_path=a_path,
        b_path=b_path,
        a_tokens=a_tokens,
        b_tokens=b_tokens,
        a_score=a_score,
        b_score=b_score,
        a_lint=a_lint,
        b_lint=b_lint,
        a_scan=a_scan,
        b_scan=b_scan,
        unified_diff=unified,
        section_deltas=deltas,
    )
