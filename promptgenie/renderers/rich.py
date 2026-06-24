"""Shared Rich terminal rendering utilities.

Color mode resolution order (highest priority first):
  1. Explicit ``--color`` CLI flag passed to ``init_renderer()``
  2. ``FORCE_COLOR=1`` environment variable  → force color on
  3. ``NO_COLOR`` environment variable (any value) → force color off
  4. stdout TTY detection → auto

When stdout is not a TTY (pipe / file redirect) the console automatically
omits Rich markup/panels, making JSON/SARIF output clean.  Diagnostic
messages (config paths, status lines) are written to *stderr* via
``diag_console`` so they never pollute piped structured output.
"""

from __future__ import annotations

import os
from enum import Enum

from rich import box  # noqa: F401  — re-exported for command modules
from rich.console import Console
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

# ---------------------------------------------------------------------------
# Color mode
# ---------------------------------------------------------------------------


class ColorMode(str, Enum):
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


def _resolve_color(mode: ColorMode | str) -> bool | None:
    """Return Rich's ``force_terminal`` / ``no_color`` pair as a single bool.

    Returns
    -------
    True  → force color on  (``force_terminal=True``)
    False → force color off (``no_color=True``)
    None  → let Rich auto-detect (TTY check)
    """
    mode = ColorMode(mode)
    if mode == ColorMode.ALWAYS:
        return True
    if mode == ColorMode.NEVER:
        return False
    # AUTO: check env vars first, then let Rich decide
    if os.environ.get("FORCE_COLOR", ""):
        return True
    if "NO_COLOR" in os.environ:
        return False
    return None  # Rich auto-detects via isatty()


def make_console(
    mode: ColorMode | str = ColorMode.AUTO,
    stderr: bool = False,
) -> Console:
    """Create a ``Console`` respecting *mode* and env-var overrides."""
    resolved = _resolve_color(mode)
    kwargs: dict = {"stderr": stderr}
    if resolved is True:
        kwargs["force_terminal"] = True
    elif resolved is False:
        kwargs["no_color"] = True
        kwargs["highlight"] = False
    return Console(**kwargs)


# ---------------------------------------------------------------------------
# Module-level singletons (mutated by init_renderer)
# ---------------------------------------------------------------------------

# stdout console — used for primary output (Rich panels, tables)
console: Console = make_console(ColorMode.AUTO, stderr=False)

# stderr console — used for diagnostic messages (config paths, status) so
# they never pollute piped JSON/SARIF output
diag_console: Console = make_console(ColorMode.AUTO, stderr=True)


def init_renderer(mode: ColorMode | str = ColorMode.AUTO) -> None:
    """Re-initialise both consoles for *mode*.

    Call this once at CLI startup after the ``--color`` flag is resolved.
    All command modules import ``console`` / ``diag_console`` by reference,
    so reassigning the module-level names here updates every caller.
    """
    global console, diag_console  # noqa: PLW0603
    import promptgenie.renderers.rich as _self

    _self.console = make_console(mode, stderr=False)
    _self.diag_console = make_console(mode, stderr=True)


def is_structured_mode(output_format: str) -> bool:
    """Return True when stdout should carry only machine-readable data.

    In structured mode commands must:
    - Send all data to stdout via ``click.echo()`` / ``print()``
    - Send diagnostics / status lines to ``diag_console`` (stderr)
    - Suppress Rich panels and status spinners on stdout
    """
    return output_format in ("json", "sarif", "yaml", "ndjson")


# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------

SEVERITY_COLORS = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan", "INFO": "dim"}
RISK_COLORS = {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan"}
SCORE_COLORS = [(80, "green"), (60, "yellow"), (0, "red")]


def score_color(n: int) -> str:
    for threshold, color in SCORE_COLORS:
        if n >= threshold:
            return color
    return "red"


# ---------------------------------------------------------------------------
# Rich format helpers
# ---------------------------------------------------------------------------


def format_lint_issues(result) -> str:  # type: ignore[no-untyped-def]
    if not result.issues:
        return "[green]No issues found.[/green]"
    lines = []
    for issue in result.issues:
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lines.append(f"[{color}][{issue.severity}][/{color}] [{issue.code}] {issue.message}")
        if issue.suggestion:
            lines.append(f"  [dim]→ {issue.suggestion}[/dim]")
    return "\n".join(lines)


def format_scan_findings(result) -> str:  # type: ignore[no-untyped-def]
    if not result.findings:
        return "[green]No findings.[/green]"
    lines = []
    for f in result.findings:
        color = RISK_COLORS.get(f.risk, "white")
        lines.append(f"[{color}][{f.risk}][/{color}] [{f.code}] {f.message}")
        if f.recommendation:
            lines.append(f"  [dim]→ {f.recommendation}[/dim]")
    return "\n".join(lines)


def delta_str(n: int, invert: bool = False) -> str:
    """Coloured +/- string for a pre-computed integer delta."""
    color = (
        "green" if (n > 0 and not invert) or (n < 0 and invert) else ("red" if n != 0 else "dim")
    )
    prefix = "+" if n > 0 else ""
    return f"[{color}]{prefix}{n}[/{color}]"


def delta_ab(a: int, b: int, invert: bool = False) -> str:
    """Coloured +/- string for b - a (used in adapt summary table)."""
    d = b - a
    color = (
        "green" if (d > 0 and not invert) or (d < 0 and invert) else ("red" if d != 0 else "dim")
    )
    prefix = "+" if d > 0 else ""
    return f"[{color}]{prefix}{d}[/{color}]"
