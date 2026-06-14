"""event_bus.py — Per-execution synchronous event dispatcher.

The ``EventBus`` is a lightweight pub/sub dispatcher.  One bus is created
per run (or per command invocation) and passed down the call stack so
subscribers can be attached before the first event fires.

Design notes
------------
- Synchronous only.  No threads, no asyncio bridges.  Async commands
  collect events and flush them after ``await``.
- No global state.  Each call site creates its own bus, keeping tests
  isolated and preventing cross-run contamination.
- Catch-all subscription via ``subscribe_all`` for audit / telemetry
  listeners that need every event regardless of kind.
- ``emit_to`` convenience method pairs a bus with a formatter so
  commands can write ``bus.emit_to(event, formatter, file)`` in one call.

Public API
----------
  ``EventBus``              — dispatcher (create one per run)
  ``EventBus.subscribe``    — listen to a specific EventKind
  ``EventBus.subscribe_all``— listen to every EventKind
  ``EventBus.emit``         — dispatch to all matching listeners
  ``EventBus.emit_to``      — dispatch + format + write in one call
  ``EventBus.collected``    — all events emitted so far (for tests)
  ``EventBus.clear``        — reset state (for test teardown)
"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import IO, Any, Callable

from promptgenie.core.events import Event, EventKind

Listener = Callable[[Event], None]


class EventBus:
    """Synchronous per-run event dispatcher.

    Example
    -------
    >>> bus = EventBus()
    >>> tokens: list[str] = []
    >>> bus.subscribe(EventKind.RUN_TOKEN, lambda e: tokens.append(e.text))
    >>> bus.emit(Event(EventKind.RUN_TOKEN, {"text": "hi"}))
    >>> tokens
    ['hi']
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = defaultdict(list)
        self._catch_all: list[Listener] = []
        self._collected: list[Event] = []

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, kind: EventKind | str, fn: Listener) -> None:
        """Register *fn* to be called whenever *kind* is emitted."""
        key = kind.value if isinstance(kind, EventKind) else str(kind)
        self._listeners[key].append(fn)

    def subscribe_all(self, fn: Listener) -> None:
        """Register *fn* to be called for every emitted event."""
        self._catch_all.append(fn)

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    def emit(self, event: Event) -> None:
        """Dispatch *event* to all matching subscribers."""
        self._collected.append(event)
        for fn in self._catch_all:
            fn(event)
        for fn in self._listeners.get(event.kind.value, []):
            fn(event)

    def emit_to(
        self,
        event: Event,
        formatter: Any,
        out: IO[str] = sys.stdout,
        *,
        end: str = "\n",
        flush: bool = True,
    ) -> None:
        """Dispatch *event* then write the formatted string to *out*.

        If the formatter returns ``None`` the event is still dispatched to
        subscribers — only the I/O write is suppressed.
        """
        self.emit(event)
        line = formatter.format(event)
        if line is not None:
            out.write(line + end)
            if flush:
                out.flush()

    # ------------------------------------------------------------------
    # Inspection (primarily for tests)
    # ------------------------------------------------------------------

    @property
    def collected(self) -> list[Event]:
        """All events emitted to this bus, in order."""
        return list(self._collected)

    def of_kind(self, kind: EventKind) -> list[Event]:
        """Return all collected events of *kind*."""
        return [e for e in self._collected if e.kind == kind]

    def clear(self) -> None:
        """Reset collected events and all subscriptions."""
        self._collected.clear()
        self._listeners.clear()
        self._catch_all.clear()

    def __len__(self) -> int:
        return len(self._collected)

    def __repr__(self) -> str:
        return f"EventBus(collected={len(self._collected)})"
