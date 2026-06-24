"""history_db.py — SQLite-backed prompt run history with deduplication.

Schema
------
  runs(
    id           TEXT PRIMARY KEY,   -- UUID run-id
    spec_name    TEXT,
    provider     TEXT,
    model        TEXT,
    prompt_hash  TEXT,               -- SHA-256 of the rendered prompt
    response_hash TEXT,              -- SHA-256 of the response
    prompt_text  TEXT,
    response_text TEXT,
    status       TEXT,               -- ok | error | dry_run
    started_at   TEXT,               -- ISO-8601
    finished_at  TEXT,
    duration_s   REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd     REAL,
    tags         TEXT,               -- JSON array
    extra        TEXT                -- JSON object
  )

Public API
----------
  ``HistoryDB``             — context manager, thin SQLite wrapper
  ``HistoryRecord``         — dataclass for a single run row
  ``open_history_db()``     → HistoryDB
  ``write_run(record)``     → str  (run_id)
  ``list_runs(limit, ...)`` → list[HistoryRecord]
  ``get_run(run_id)``       → HistoryRecord | None
  ``search_runs(query)``    → list[HistoryRecord]
  ``export_runs(fmt, ...)`` → str  (json|csv|ndjson)
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH = Path("~/.local/share/promptgenie/history.db").expanduser()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    spec_name     TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    prompt_hash   TEXT NOT NULL DEFAULT '',
    response_hash TEXT NOT NULL DEFAULT '',
    prompt_text   TEXT NOT NULL DEFAULT '',
    response_text TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'ok',
    started_at    TEXT NOT NULL DEFAULT '',
    finished_at   TEXT NOT NULL DEFAULT '',
    duration_s    REAL NOT NULL DEFAULT 0.0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0.0,
    tags          TEXT NOT NULL DEFAULT '[]',
    extra         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_prompt_hash ON runs(prompt_hash);
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class HistoryRecord:
    id: str
    spec_name: str
    provider: str
    model: str
    prompt_hash: str
    response_hash: str
    prompt_text: str
    response_text: str
    status: str
    started_at: str
    finished_at: str
    duration_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "spec_name": self.spec_name,
            "provider": self.provider,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "response_hash": self.response_hash,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "tags": self.tags,
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> HistoryRecord:
        return HistoryRecord(
            id=row["id"],
            spec_name=row["spec_name"],
            provider=row["provider"],
            model=row["model"],
            prompt_hash=row["prompt_hash"],
            response_hash=row["response_hash"],
            prompt_text=row["prompt_text"],
            response_text=row["response_text"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            duration_s=row["duration_s"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cost_usd=row["cost_usd"],
            tags=json.loads(row["tags"] or "[]"),
            extra=json.loads(row["extra"] or "{}"),
        )


# ---------------------------------------------------------------------------
# HistoryDB class
# ---------------------------------------------------------------------------


class HistoryDB:
    """Thin SQLite wrapper around the history database."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> HistoryDB:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Write ────────────────────────────────────────────────────────────────

    def write_run(
        self,
        *,
        spec_name: str = "",
        provider: str = "",
        model: str = "",
        prompt_text: str = "",
        response_text: str = "",
        status: str = "ok",
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_s: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        tags: list[str] | None = None,
        extra: dict | None = None,
        run_id: str | None = None,
    ) -> str:
        rid = run_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO runs
              (id, spec_name, provider, model, prompt_hash, response_hash,
               prompt_text, response_text, status, started_at, finished_at,
               duration_s, input_tokens, output_tokens, cost_usd, tags, extra)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rid,
                spec_name,
                provider,
                model,
                _hash(prompt_text),
                _hash(response_text),
                prompt_text,
                response_text,
                status,
                started_at or now,
                finished_at or now,
                duration_s,
                input_tokens,
                output_tokens,
                cost_usd,
                json.dumps(tags or []),
                json.dumps(extra or {}),
            ),
        )
        self._conn.commit()
        return rid

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_run(self, run_id: str) -> HistoryRecord | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return HistoryRecord._from_row(row) if row else None

    def list_runs(
        self,
        limit: int = 20,
        *,
        provider: str | None = None,
        status: str | None = None,
        spec_name: str | None = None,
    ) -> list[HistoryRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if spec_name:
            clauses.append("spec_name LIKE ?")
            params.append(f"%{spec_name}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM runs {where} ORDER BY started_at DESC LIMIT ?",  # nosec B608 - hardcoded predicates; values bound via ? params
            params,
        ).fetchall()
        return [HistoryRecord._from_row(r) for r in rows]

    def search_runs(self, query: str, limit: int = 20) -> list[HistoryRecord]:
        """Full-text search across spec_name, provider, model, prompt_text."""
        like = f"%{query}%"
        rows = self._conn.execute(
            """SELECT * FROM runs
               WHERE spec_name LIKE ? OR provider LIKE ? OR model LIKE ? OR prompt_text LIKE ?
               ORDER BY started_at DESC LIMIT ?""",
            (like, like, like, like, limit),
        ).fetchall()
        return [HistoryRecord._from_row(r) for r in rows]

    def find_duplicates(self, prompt_text: str) -> list[HistoryRecord]:
        """Find runs with the same prompt hash (content deduplication)."""
        h = _hash(prompt_text)
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE prompt_hash = ? ORDER BY started_at DESC",
            (h,),
        ).fetchall()
        return [HistoryRecord._from_row(r) for r in rows]

    def delete_run(self, run_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def total_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])

    # ── Export ───────────────────────────────────────────────────────────────

    def export(self, fmt: str = "json", limit: int = 100) -> str:
        records = self.list_runs(limit=limit)
        if fmt == "json":
            return json.dumps([r.to_dict() for r in records], indent=2)
        if fmt == "ndjson":
            return "\n".join(json.dumps(r.to_dict()) for r in records)
        if fmt == "csv":
            out = io.StringIO()
            if not records:
                return ""
            w = csv.DictWriter(out, fieldnames=list(records[0].to_dict().keys()))
            w.writeheader()
            w.writerows(r.to_dict() for r in records)
            return out.getvalue()
        raise ValueError(f"Unknown format {fmt!r}. Use json, ndjson, or csv.")


# ---------------------------------------------------------------------------
# Context manager shortcut
# ---------------------------------------------------------------------------


@contextmanager
def open_history_db(db_path: Path | None = None) -> Generator[HistoryDB, None, None]:
    db = HistoryDB(db_path)
    try:
        yield db
    finally:
        db.close()
