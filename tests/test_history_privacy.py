"""Tests for history privacy defaults (metadata-only persistence)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import promptgenie.core.history as history_mod
from promptgenie.core.config import SecurityConfig, validate_workspace_config
from promptgenie.core.history import RunWriter
from promptgenie.core.history_db import HistoryDB

_SECRET = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _writer_path(tmp_path: Path, monkeypatch, **kw) -> Path:
    monkeypatch.setattr(history_mod, "_RUNS_DIR", tmp_path / "runs")
    w = RunWriter(
        run_id="testrun1",
        spec_name="s",
        target="claude",
        provider="anthropic",
        model="claude",
        dry_run=False,
        **kw,
    )
    w.write_token("hello ")
    w.write_token("world")
    w.finish(status="ok", completion_tokens=2)
    return (tmp_path / "runs").rglob("testrun1.ndjson").__next__()


# ---------------------------------------------------------------------------
# NDJSON RunWriter — the store populated on every run
# ---------------------------------------------------------------------------


class TestRunWriterMetadataDefault:
    def test_default_omits_prompt_and_response_bodies(self, tmp_path, monkeypatch):
        path = _writer_path(tmp_path, monkeypatch, prompt="my secret prompt")
        evs = _events(path)
        start = next(e for e in evs if e["event"] == "start")
        done = next(e for e in evs if e["event"] == "done")
        assert start["prompt"] == ""
        assert done["response"] == ""
        # No raw token events persisted by default.
        assert not [e for e in evs if e["event"] == "token"]

    def test_default_still_records_hashes_and_metadata(self, tmp_path, monkeypatch):
        path = _writer_path(tmp_path, monkeypatch, prompt="my prompt")
        evs = _events(path)
        start = next(e for e in evs if e["event"] == "start")
        done = next(e for e in evs if e["event"] == "done")
        assert start["prompt_hash"] and len(start["prompt_hash"]) == 64
        assert done["response_hash"] and len(done["response_hash"]) == 64
        assert done["completion_tokens"] == 2
        assert done["response_length"] == len("hello world")
        assert start["store_content"] is False

    def test_opt_in_persists_redacted_bodies_and_tokens(self, tmp_path, monkeypatch):
        path = _writer_path(tmp_path, monkeypatch, prompt="see " + _SECRET, store_content=True)
        evs = _events(path)
        start = next(e for e in evs if e["event"] == "start")
        done = next(e for e in evs if e["event"] == "done")
        assert start["prompt"]  # body present when opted in
        assert _SECRET not in start["prompt"]  # but redacted
        assert "REDACTED" in start["prompt"]
        assert done["response"] == "hello world"
        assert [e for e in evs if e["event"] == "token"]  # token events present


# ---------------------------------------------------------------------------
# SQLite history_db
# ---------------------------------------------------------------------------


class TestHistoryDBPrivacy:
    def test_default_stores_no_bodies(self, tmp_path):
        db_path = tmp_path / "history.db"
        with HistoryDB(db_path) as db:
            rid = db.write_run(spec_name="s", prompt_text="secret prompt", response_text="answer")
            rec = db.get_run(rid)
        assert rec is not None
        assert rec.prompt_text == ""
        assert rec.response_text == ""
        assert rec.prompt_hash and rec.response_hash  # hashes retained

    def test_opt_in_stores_redacted_bodies(self, tmp_path):
        db_path = tmp_path / "history.db"
        with HistoryDB(db_path) as db:
            rid = db.write_run(
                spec_name="s",
                prompt_text="key " + _SECRET,
                response_text="ok",
                store_content=True,
            )
            rec = db.get_run(rid)
        assert rec is not None
        assert rec.prompt_text  # stored
        assert _SECRET not in rec.prompt_text  # redacted
        assert rec.response_text == "ok"

    def test_db_file_permissions_owner_only(self, tmp_path):
        db_path = tmp_path / "sub" / "history.db"
        with HistoryDB(db_path):
            pass
        mode = stat.S_IMODE(db_path.stat().st_mode)
        assert mode == 0o600, oct(mode)
        dir_mode = stat.S_IMODE(db_path.parent.stat().st_mode)
        assert dir_mode == 0o700, oct(dir_mode)


# ---------------------------------------------------------------------------
# Config plumbing
# ---------------------------------------------------------------------------


class TestHistoryConfig:
    def test_security_config_default_is_private(self):
        assert SecurityConfig().store_history_content is False

    def test_workspace_schema_accepts_key(self):
        errors, _ = validate_workspace_config({"security": {"store_history_content": True}})
        assert errors == [], errors

    def test_workspace_schema_rejects_non_bool(self):
        errors, _ = validate_workspace_config({"security": {"store_history_content": "yes"}})
        assert any("store_history_content" in e for e in errors), errors
