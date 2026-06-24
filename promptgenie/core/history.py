"""history.py — persist and query PromptGenie run history.

Runs are stored as NDJSON files under::

    ~/.local/share/promptgenie/runs/<YYYY-MM-DD>/<run-id>.ndjson

Each line is a JSON event object. The first line is always a ``start`` event
containing the full run metadata. Subsequent lines are ``token`` events
(during streaming) and the final line is a ``done`` event with usage stats.

Public API
----------
  ``RunRecord``            — dataclass for the final run summary
  ``open_run_writer(run_id, spec_name)``   → RunWriter context manager
  ``list_runs(limit)``     → list[RunRecord] newest first
  ``load_run(run_id)``     → RunRecord | None
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from promptgenie.core.llm_analyzer import redact_secrets

_RUNS_DIR = Path("~/.local/share/promptgenie/runs").expanduser()

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RunRecord:
    run_id: str
    spec_name: str
    target: str
    provider: str
    model: str
    started_at: str  # ISO 8601
    finished_at: str
    duration_s: float
    prompt_tokens: int
    completion_tokens: int
    status: str  # ok | error | dry_run
    error: str
    response: str  # full assembled response text
    dry_run: bool
    schema_version: str = SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Writer (context manager)
# ---------------------------------------------------------------------------


class RunWriter:
    """Write events to a run NDJSON file."""

    def __init__(
        self,
        run_id: str,
        spec_name: str,
        target: str,
        provider: str,
        model: str,
        dry_run: bool,
        prompt: str = "",
    ) -> None:
        self.run_id = run_id
        self.spec_name = spec_name
        self.target = target
        self.provider = provider
        self.model = model
        self.dry_run = dry_run
        # Redact secrets before the prompt is ever written to disk (S-4).
        self.prompt = redact_secrets(prompt)[0] if prompt else ""
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._start_time = time.monotonic()
        self._tokens: list[str] = []
        self._path: Path | None = None
        self._file: Any = None

    def _ensure_file(self) -> None:
        if self._file is not None:
            return
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_dir = _RUNS_DIR / date_str
        # Restrict directory permissions: run history may contain prompt/response
        # text. mode= is masked by umask, so chmod explicitly afterwards (S-4).
        day_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for d in (_RUNS_DIR, day_dir):
            with contextlib.suppress(OSError):
                os.chmod(d, 0o700)
        self._path = day_dir / f"{self.run_id}.ndjson"
        # Create the file with 0o600 from the start (open() honours umask, so
        # also chmod explicitly) before writing any sensitive content.
        fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        self._file = os.fdopen(fd, "w", encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(self._path, 0o600)
        # Write start event (prompt already redacted in __init__).
        self._write_event(
            "start",
            {
                "run_id": self.run_id,
                "spec_name": self.spec_name,
                "target": self.target,
                "provider": self.provider,
                "model": self.model,
                "dry_run": self.dry_run,
                "started_at": self.started_at,
                "prompt": self.prompt,
                "schema_version": SCHEMA_VERSION,
            },
        )

    def _write_event(self, event_type: str, data: dict[str, Any]) -> None:
        line = json.dumps({"event": event_type, "ts": time.time(), **data})
        if self._file:
            self._file.write(line + "\n")
            self._file.flush()

    def write_token(self, token: str) -> None:
        self._ensure_file()
        self._tokens.append(token)
        self._write_event("token", {"text": token})

    def write_warning(self, message: str) -> None:
        self._ensure_file()
        self._write_event("warning", {"message": message})

    def write_tool_call(self, tool_name: str, args: dict[str, Any]) -> None:
        self._ensure_file()
        self._write_event("tool_call", {"tool": tool_name, "args": args})

    def write_error(self, message: str) -> None:
        self._ensure_file()
        self._write_event("error", {"message": message})

    def finish(
        self,
        status: str = "ok",
        error: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> RunRecord:
        self._ensure_file()
        finished_at = datetime.now(timezone.utc).isoformat()
        duration = time.monotonic() - self._start_time
        response = "".join(self._tokens)
        # Redact secrets from the final assembled response before persisting (S-4).
        redacted_response = redact_secrets(response)[0] if response else ""
        self._write_event(
            "done",
            {
                "status": status,
                "error": error,
                "finished_at": finished_at,
                "duration_s": round(duration, 3),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "response_length": len(response),
                "response": redacted_response,
            },
        )
        if self._file:
            self._file.close()
            self._file = None
        return RunRecord(
            run_id=self.run_id,
            spec_name=self.spec_name,
            target=self.target,
            provider=self.provider,
            model=self.model,
            started_at=self.started_at,
            finished_at=finished_at,
            duration_s=round(duration, 3),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            status=status,
            error=error,
            response=response,
            dry_run=self.dry_run,
        )


@contextmanager
def open_run_writer(
    *,
    spec_name: str,
    target: str,
    provider: str,
    model: str,
    dry_run: bool = False,
    prompt: str = "",
) -> Generator[RunWriter, None, None]:
    """Context manager that yields a RunWriter and handles cleanup."""
    run_id = str(uuid.uuid4())[:8]
    writer = RunWriter(
        run_id=run_id,
        spec_name=spec_name,
        target=target,
        provider=provider,
        model=model,
        dry_run=dry_run,
        prompt=prompt,
    )
    try:
        yield writer
    except Exception:
        writer.write_error("Unexpected exception in run_engine")
        writer.finish(status="error")
        raise


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------


def list_runs(limit: int = 20) -> list[RunRecord]:
    """Return the *limit* most recent runs, newest first."""
    if not _RUNS_DIR.exists():
        return []

    ndjson_files: list[Path] = []
    for day_dir in sorted(_RUNS_DIR.iterdir(), reverse=True):
        if day_dir.is_dir():
            ndjson_files.extend(sorted(day_dir.glob("*.ndjson"), reverse=True))
        if len(ndjson_files) >= limit:
            break

    records: list[RunRecord] = []
    for f in ndjson_files[:limit]:
        rec = _parse_run_file(f)
        if rec:
            records.append(rec)
    return records


def load_run(run_id: str) -> RunRecord | None:
    """Find and return a specific run by ID."""
    if not _RUNS_DIR.exists():
        return None
    for ndjson_file in _RUNS_DIR.rglob(f"{run_id}.ndjson"):
        return _parse_run_file(ndjson_file)
    # partial match
    for ndjson_file in _RUNS_DIR.rglob("*.ndjson"):
        if ndjson_file.stem.startswith(run_id):
            return _parse_run_file(ndjson_file)
    return None


def _parse_run_file(path: Path) -> RunRecord | None:
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return None

        start_event: dict[str, Any] = {}
        done_event: dict[str, Any] = {}
        tokens: list[str] = []

        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("event") == "start":
                start_event = obj
            elif obj.get("event") == "done":
                done_event = obj
            elif obj.get("event") == "token":
                tokens.append(obj.get("text", ""))

        if not start_event:
            return None

        # Prefer the redacted full response recorded in the done event; fall
        # back to reassembling token events for older run files (S-4).
        response_text = done_event["response"] if "response" in done_event else "".join(tokens)

        return RunRecord(
            run_id=start_event.get("run_id", path.stem),
            spec_name=start_event.get("spec_name", ""),
            target=start_event.get("target", ""),
            provider=start_event.get("provider", ""),
            model=start_event.get("model", ""),
            started_at=start_event.get("started_at", ""),
            finished_at=done_event.get("finished_at", ""),
            duration_s=float(done_event.get("duration_s", 0)),
            prompt_tokens=int(done_event.get("prompt_tokens", 0)),
            completion_tokens=int(done_event.get("completion_tokens", 0)),
            status=done_event.get("status", "unknown"),
            error=done_event.get("error", ""),
            response=response_text,
            dry_run=bool(start_event.get("dry_run", False)),
        )
    except Exception:
        return None
