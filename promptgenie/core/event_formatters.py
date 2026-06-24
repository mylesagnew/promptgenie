"""event_formatters.py — Pluggable output formatters for Event objects.

A formatter receives an ``Event`` and returns a string to write, or ``None``
to suppress that event entirely.  This is the single extension point for
adding new output destinations (webhook, log file, remote telemetry, etc.)
without touching command code.

Built-in formatters
-------------------
  NDJSONFormatter    — one JSON line per event; all kinds pass through
  TokenOnlyFormatter — raw token text only; every other kind suppressed
  RichFormatter      — human-readable Rich markup; tokens suppressed
  SilentFormatter    — suppresses all events (test / dry-run use)

Protocol
--------
Any object with a ``format(event: Event) -> str | None`` method satisfies
``EventFormatter``.  No base class required.

Usage
-----
  fmt = NDJSONFormatter()
  line = fmt.format(event)
  if line is not None:
      sys.stdout.write(line + "\\n")
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from promptgenie.core.events import Event, EventKind


@runtime_checkable
class EventFormatter(Protocol):
    """Structural protocol for event formatters.

    Implementors return a string (the text to output) or ``None`` to suppress.
    The caller is responsible for adding newlines and flushing.
    """

    def format(self, event: Event) -> str | None: ...


# ---------------------------------------------------------------------------
# NDJSONFormatter
# ---------------------------------------------------------------------------


class NDJSONFormatter:
    """Emit every event as a single JSON line.

    Suitable for machine consumption (CI scripts, ``jq`` pipelines, log
    aggregators).  All event kinds are included.
    """

    def format(self, event: Event) -> str | None:
        return event.to_ndjson()


# ---------------------------------------------------------------------------
# TokenOnlyFormatter
# ---------------------------------------------------------------------------


class TokenOnlyFormatter:
    """Emit only the ``text`` payload of ``run.token`` events.

    Used when streaming responses to a TTY — every other event is suppressed
    so the output looks like a plain text stream.
    """

    def format(self, event: Event) -> str | None:
        if event.kind == EventKind.RUN_TOKEN:
            return event.text
        return None


# ---------------------------------------------------------------------------
# SilentFormatter
# ---------------------------------------------------------------------------


class SilentFormatter:
    """Suppress all events.

    Useful in unit tests and batch contexts where emitted events should be
    collected but not printed.
    """

    def format(self, event: Event) -> str | None:
        return None


# ---------------------------------------------------------------------------
# RichFormatter
# ---------------------------------------------------------------------------

_SEVERITY_COLORS: dict[str, str] = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "cyan",
    "INFO": "dim",
}

_KIND_ICONS: dict[EventKind, str] = {
    EventKind.RUN_START: "▶",
    EventKind.RUN_DONE: "✓",
    EventKind.RUN_DRY: "◌",
    EventKind.RUN_WARNING: "⚠",
    EventKind.RUN_ERROR: "✗",
    EventKind.RUN_TOOL_CALL: "⚙",
    EventKind.LINT_FINDING: "●",
    EventKind.SCAN_FINDING: "⬤",
    EventKind.POLICY_PASS: "✅",
    EventKind.POLICY_VIOLATION: "❌",
    EventKind.DIFF_COMPUTED: "⟷",
    EventKind.EVAL_RESULT: "📊",
    EventKind.CI_CHECK: "🔄",
    EventKind.AUDIT_WRITE: "📝",
}


class RichFormatter:
    """Human-readable Rich markup lines for diagnostic output.

    ``run.token`` events are suppressed — those are handled inline by the TTY
    renderer.  All other events produce a single Rich-markup line.

    The output is *not* auto-printed; callers should pass it to
    ``rich.console.Console.print()`` or strip markup for plain text.
    """

    def format(self, event: Event) -> str | None:  # noqa: A003
        kind = event.kind
        icon = _KIND_ICONS.get(kind, "·")

        # Tokens are streamed inline — never emit a line here
        if kind == EventKind.RUN_TOKEN:
            return None

        if kind == EventKind.RUN_WARNING:
            return f"[yellow]{icon} {kind.value}:[/yellow] {event.message}"

        if kind == EventKind.RUN_ERROR:
            return f"[red]{icon} {kind.value}:[/red] {event.message}"

        if kind in (EventKind.RUN_START, EventKind.RUN_DONE, EventKind.RUN_DRY):
            spec = event.data.get("spec_name", "")
            extra = f" — {spec}" if spec else ""
            return f"[dim]{icon} {kind.value}{extra}[/dim]"

        if kind == EventKind.RUN_TOOL_CALL:
            name = event.data.get("name", "?")
            return f"[dim]{icon} tool_call: {name}[/dim]"

        if kind == EventKind.LINT_FINDING:
            code = event.data.get("code", "")
            sev = event.data.get("severity", "")
            msg = event.data.get("message", "")
            color = _SEVERITY_COLORS.get(sev, "dim")
            return f"[{color}]{icon} {code}[/{color}] [{sev}] {msg}"

        if kind == EventKind.SCAN_FINDING:
            code = event.data.get("code", "")
            risk = event.data.get("risk", "")
            msg = event.data.get("message", "")
            color = _SEVERITY_COLORS.get(risk, "dim")
            return f"[{color}]{icon} {code}[/{color}] [risk:{risk}] {msg}"

        if kind == EventKind.POLICY_VIOLATION:
            rule = event.data.get("rule", "")
            msg = event.data.get("message", "")
            return f"[red]{icon} policy/{rule}:[/red] {msg}"

        if kind == EventKind.POLICY_PASS:
            return f"[green]{icon} policy: all rules passed[/green]"

        if kind == EventKind.DIFF_COMPUTED:
            sections = event.data.get("section_count", "?")
            return f"[dim]{icon} diff: {sections} section(s) compared[/dim]"

        if kind == EventKind.EVAL_RESULT:
            model = event.data.get("model", "?")
            score = event.data.get("score", "?")
            return f"[dim]{icon} eval/{model}: score={score}[/dim]"

        if kind == EventKind.CI_CHECK:
            check = event.data.get("check", "?")
            passed = event.data.get("passed", True)
            mark = "✓" if passed else "✗"
            color = "green" if passed else "red"
            return f"[{color}]{mark} ci/{check}[/{color}]"

        if kind == EventKind.AUDIT_WRITE:
            row_id = event.data.get("row_id", "?")
            return f"[dim]{icon} audit: row_id={row_id}[/dim]"

        # Unknown / catch-all
        summary = ", ".join(f"{k}={v!r}" for k, v in list(event.data.items())[:3])
        return f"[dim]{icon} {kind.value}[/dim]" + (f": {summary}" if summary else "")
