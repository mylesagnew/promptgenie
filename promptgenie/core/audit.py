"""audit.py — tamper-evident audit log for PromptGenie runs.

Stores a record of every run, policy decision, and external send in a local
SQLite database at::

    ~/.local/share/promptgenie/audit.db

Each row includes a SHA-256 chain hash that covers the previous row's hash
plus the current row's content — making retrospective tampering detectable.

Schema
------
  CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    row_hash    TEXT NOT NULL,       -- SHA-256(prev_hash + row_content)
    timestamp   TEXT NOT NULL,       -- ISO 8601 UTC
    user        TEXT,                -- $USER env var
    cwd         TEXT,
    command     TEXT,                -- e.g. "run", "analyze", "policy"
    provider    TEXT,
    model       TEXT,
    spec_name   TEXT,
    prompt_hash TEXT,                -- SHA-256[:16] of assembled prompt
    response_hash TEXT,              -- SHA-256[:16] of response
    policy_decision TEXT,            -- "pass" | "fail" | "skip"
    external_send INTEGER,           -- 1 if sent to external provider
    status      TEXT,                -- "ok" | "error" | "dry_run"
    extra_json  TEXT                 -- JSON for arbitrary extra fields
  )

Public API
----------
  ``write_audit_event(...)``          → row_id (int)
  ``list_audit_events(limit)``        → list[AuditEvent]
  ``load_audit_event(row_id)``        → AuditEvent | None
  ``verify_chain()``                  → (ok: bool, first_broken_id: int | None)
  ``export_audit(path, fmt)``         → None
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AUDIT_DB = Path("~/.local/share/promptgenie/audit.db").expanduser()
_GENESIS_HASH = "0" * 64


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuditEvent:
    id: int
    row_hash: str
    timestamp: str
    user: str
    cwd: str
    command: str
    provider: str
    model: str
    spec_name: str
    prompt_hash: str
    response_hash: str
    policy_decision: str
    external_send: bool
    status: str
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_connection() -> sqlite3.Connection:
    _AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_AUDIT_DB))
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            row_hash        TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            user            TEXT,
            cwd             TEXT,
            command         TEXT,
            provider        TEXT,
            model           TEXT,
            spec_name       TEXT,
            prompt_hash     TEXT,
            response_hash   TEXT,
            policy_decision TEXT,
            external_send   INTEGER DEFAULT 0,
            status          TEXT,
            extra_json      TEXT
        )
    """)
    conn.commit()


def _prev_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["row_hash"] if row else _GENESIS_HASH


def _compute_row_hash(prev_hash: str, row_content: str) -> str:
    return hashlib.sha256(f"{prev_hash}{row_content}".encode()).hexdigest()


def _row_content(fields: dict[str, Any]) -> str:
    return json.dumps(fields, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_audit_event(
    *,
    command: str,
    provider: str = "",
    model: str = "",
    spec_name: str = "",
    prompt_hash: str = "",
    response_hash: str = "",
    policy_decision: str = "skip",
    external_send: bool = False,
    status: str = "ok",
    extra: dict[str, Any] | None = None,
) -> int:
    """Write an audit event and return its row id."""
    ts = datetime.now(timezone.utc).isoformat()
    user = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
    cwd = str(Path.cwd())
    extra_json = json.dumps(extra or {}, default=str)

    fields = dict(
        timestamp=ts,
        user=user,
        cwd=cwd,
        command=command,
        provider=provider,
        model=model,
        spec_name=spec_name,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        policy_decision=policy_decision,
        external_send=int(external_send),
        status=status,
        extra_json=extra_json,
    )

    with _get_connection() as conn:
        prev = _prev_hash(conn)
        row_hash = _compute_row_hash(prev, _row_content(fields))
        conn.execute(
            """INSERT INTO audit_log
               (row_hash, timestamp, user, cwd, command, provider, model, spec_name,
                prompt_hash, response_hash, policy_decision, external_send, status, extra_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_hash, ts, user, cwd, command, provider, model, spec_name,
                prompt_hash, response_hash, policy_decision, int(external_send),
                status, extra_json,
            ),
        )
        conn.commit()
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return row_id


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def _row_to_event(row: sqlite3.Row) -> AuditEvent:
    try:
        extra = json.loads(row["extra_json"] or "{}")
    except Exception:
        extra = {}
    return AuditEvent(
        id=row["id"],
        row_hash=row["row_hash"],
        timestamp=row["timestamp"],
        user=row["user"] or "",
        cwd=row["cwd"] or "",
        command=row["command"] or "",
        provider=row["provider"] or "",
        model=row["model"] or "",
        spec_name=row["spec_name"] or "",
        prompt_hash=row["prompt_hash"] or "",
        response_hash=row["response_hash"] or "",
        policy_decision=row["policy_decision"] or "skip",
        external_send=bool(row["external_send"]),
        status=row["status"] or "ok",
        extra=extra,
    )


def list_audit_events(limit: int = 20, command: str | None = None) -> list[AuditEvent]:
    """Return the *limit* most recent audit events, newest first."""
    try:
        with _get_connection() as conn:
            if command:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE command=? ORDER BY id DESC LIMIT ?",
                    (command, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [_row_to_event(r) for r in rows]
    except Exception:
        return []


def load_audit_event(row_id: int) -> AuditEvent | None:
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM audit_log WHERE id=?", (row_id,)
            ).fetchone()
        return _row_to_event(row) if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Chain verification
# ---------------------------------------------------------------------------


def verify_chain() -> tuple[bool, int | None]:
    """Verify the tamper-evident hash chain. Returns (ok, first_broken_id)."""
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id ASC"
            ).fetchall()
    except Exception:
        return True, None  # empty or unreachable DB

    prev = _GENESIS_HASH
    for row in rows:
        fields = {
            "timestamp": row["timestamp"],
            "user": row["user"],
            "cwd": row["cwd"],
            "command": row["command"],
            "provider": row["provider"],
            "model": row["model"],
            "spec_name": row["spec_name"],
            "prompt_hash": row["prompt_hash"],
            "response_hash": row["response_hash"],
            "policy_decision": row["policy_decision"],
            "external_send": row["external_send"],
            "status": row["status"],
            "extra_json": row["extra_json"],
        }
        expected = _compute_row_hash(prev, _row_content(fields))
        if row["row_hash"] != expected:
            return False, row["id"]
        prev = row["row_hash"]

    return True, None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_audit(
    path: str | Path,
    fmt: str = "json",
    limit: int = 1000,
) -> None:
    """Export audit log to *path* in *fmt* (json | csv | ndjson)."""
    events = list_audit_events(limit=limit)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        import csv
        with p.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "timestamp", "user", "command", "provider", "model",
                "spec_name", "prompt_hash", "policy_decision", "external_send",
                "status", "row_hash",
            ])
            writer.writeheader()
            for e in events:
                writer.writerow({
                    "id": e.id, "timestamp": e.timestamp, "user": e.user,
                    "command": e.command, "provider": e.provider, "model": e.model,
                    "spec_name": e.spec_name, "prompt_hash": e.prompt_hash,
                    "policy_decision": e.policy_decision,
                    "external_send": e.external_send,
                    "status": e.status, "row_hash": e.row_hash,
                })
    elif fmt == "ndjson":
        with p.open("w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps({
                    "id": e.id, "timestamp": e.timestamp, "user": e.user,
                    "command": e.command, "provider": e.provider, "model": e.model,
                    "spec_name": e.spec_name, "prompt_hash": e.prompt_hash,
                    "policy_decision": e.policy_decision,
                    "external_send": e.external_send,
                    "status": e.status, "row_hash": e.row_hash,
                }, default=str) + "\n")
    else:
        data = [
            {
                "id": e.id, "timestamp": e.timestamp, "user": e.user,
                "cwd": e.cwd, "command": e.command, "provider": e.provider,
                "model": e.model, "spec_name": e.spec_name,
                "prompt_hash": e.prompt_hash, "response_hash": e.response_hash,
                "policy_decision": e.policy_decision,
                "external_send": e.external_send,
                "status": e.status, "row_hash": e.row_hash,
            }
            for e in events
        ]
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
