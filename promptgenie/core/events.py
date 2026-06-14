"""events.py — Unified event model for PromptGenie.

Every observable lifecycle moment in PromptGenie is expressed as an ``Event``.
Commands *emit*; formatters and audit subscribers *consume*.

Event kinds follow a ``<domain>.<action>`` naming scheme::

  run.*        — execution pipeline (start, token, done, warning, error, tool_call, dry)
  lint.*       — linter findings
  scan.*       — security scanner findings
  policy.*     — policy gate outcomes
  diff.*       — diff computation
  eval.*       — evaluation matrix results
  ci.*         — CI pipeline checks
  audit.*      — audit log writes

Public API
----------
  ``EventKind``              — typed string enum of all known event kinds
  ``Event``                  — immutable, frozen dataclass; serialises to NDJSON
  ``Event.from_run_event()`` — bridge from the legacy ``RunEvent`` in run_engine
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    """All event kinds emitted by PromptGenie.

    The string value is the canonical ``event`` field in NDJSON output.
    """

    # ── Run pipeline ──────────────────────────────────────────────────────────
    RUN_START = "run.start"
    RUN_TOKEN = "run.token"
    RUN_WARNING = "run.warning"
    RUN_ERROR = "run.error"
    RUN_TOOL_CALL = "run.tool_call"
    RUN_DONE = "run.done"
    RUN_DRY = "run.dry"

    # ── Analysis pipeline ────────────────────────────────────────────────────
    LINT_FINDING = "lint.finding"
    SCAN_FINDING = "scan.finding"

    # ── Policy gate ──────────────────────────────────────────────────────────
    POLICY_PASS = "policy.pass"
    POLICY_VIOLATION = "policy.violation"

    # ── Diff ─────────────────────────────────────────────────────────────────
    DIFF_COMPUTED = "diff.computed"

    # ── Evaluation & CI ──────────────────────────────────────────────────────
    EVAL_RESULT = "eval.result"
    CI_CHECK = "ci.check"

    # ── Audit ─────────────────────────────────────────────────────────────────
    AUDIT_WRITE = "audit.write"

    # ── Catch-all ────────────────────────────────────────────────────────────
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> "EventKind":
        return cls.UNKNOWN


# Mapping from legacy RunEvent.event strings → EventKind
_LEGACY_KIND_MAP: dict[str, EventKind] = {
    "start":     EventKind.RUN_START,
    "token":     EventKind.RUN_TOKEN,
    "warning":   EventKind.RUN_WARNING,
    "error":     EventKind.RUN_ERROR,
    "tool_call": EventKind.RUN_TOOL_CALL,
    "done":      EventKind.RUN_DONE,
}


@dataclass(frozen=True)
class Event:
    """An immutable lifecycle event with a typed kind and arbitrary payload.

    ``data`` holds all event-specific fields.  Keys are kept flat to make
    NDJSON lines easy to ``jq``-filter downstream.

    Examples
    --------
    >>> e = Event(EventKind.RUN_TOKEN, {"text": "hello"}, run_id="abc123")
    >>> e.to_ndjson()
    '{"event": "run.token", "run_id": "abc123", "ts": ..., "text": "hello"}'
    """

    kind: EventKind
    data: dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    ts: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a flat dict suitable for JSON serialisation."""
        return {
            "event": self.kind.value,
            "run_id": self.run_id,
            "ts": self.ts,
            **self.data,
        }

    def to_ndjson(self) -> str:
        """Return a single-line JSON string (no trailing newline)."""
        return json.dumps(self.to_dict())

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_run_event(cls, run_event: Any, run_id: str = "") -> "Event":
        """Coerce a legacy ``RunEvent`` (from run_engine) into a unified Event.

        This bridge method lets existing code that produces ``RunEvent`` objects
        participate in the new event bus without a full rewrite.
        """
        legacy_kind: str = getattr(run_event, "event", "unknown")
        legacy_data: dict[str, Any] = dict(getattr(run_event, "data", {}))
        kind = _LEGACY_KIND_MAP.get(legacy_kind, EventKind.UNKNOWN)
        return cls(kind=kind, data=legacy_data, run_id=run_id)

    # ------------------------------------------------------------------
    # Typed field accessors (sugar for common data keys)
    # ------------------------------------------------------------------

    @property
    def text(self) -> str:
        """Token text for ``run.token`` events."""
        return str(self.data.get("text", ""))

    @property
    def message(self) -> str:
        """Human-readable message for warning / error events."""
        return str(self.data.get("message", ""))

    @property
    def status(self) -> str:
        """Status string for ``run.done`` / ``run.dry`` events."""
        return str(self.data.get("status", ""))
