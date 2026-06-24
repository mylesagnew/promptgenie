"""Tests for promptgenie.commands.completion — shell completion installer."""

from __future__ import annotations

from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.commands.completion import (
    _build_completion_cache,
    _read_cache,
    _write_cache,
)


class TestCompletionCache:
    def test_build_cache_returns_dict(self):
        cache = _build_completion_cache()
        assert isinstance(cache, dict)
        assert "targets" in cache
        assert "templates" in cache
        assert "context_packs" in cache

    def test_cache_targets_non_empty(self):
        cache = _build_completion_cache()
        assert len(cache["targets"]) > 0

    def test_cache_templates_non_empty(self):
        cache = _build_completion_cache()
        assert len(cache["templates"]) > 0

    def test_write_and_read_cache(self, tmp_path, monkeypatch):
        import promptgenie.commands.completion as comp

        monkeypatch.setattr(comp, "_CACHE_DIR", tmp_path)
        monkeypatch.setattr(comp, "_CACHE_FILE", tmp_path / "completions.json")
        data = {"targets": ["claude"], "templates": ["agentic-task"]}
        _write_cache(data)
        result = _read_cache()
        assert result == data

    def test_read_cache_missing_returns_none(self, tmp_path, monkeypatch):
        import promptgenie.commands.completion as comp

        monkeypatch.setattr(comp, "_CACHE_FILE", tmp_path / "no_such.json")
        assert _read_cache() is None


class TestCompletionStatusCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_status_exits_0(self):
        result = self.runner.invoke(cli, ["completion", "status"])
        assert result.exit_code == 0

    def test_status_shows_shells(self):
        result = self.runner.invoke(cli, ["completion", "status"])
        assert "zsh" in result.output or "bash" in result.output or "fish" in result.output


class TestRefreshCacheCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_refresh_cache_exits_0(self):
        result = self.runner.invoke(cli, ["completion", "refresh-cache"])
        assert result.exit_code == 0

    def test_refresh_cache_shows_counts(self):
        result = self.runner.invoke(cli, ["completion", "refresh-cache"])
        assert "targets" in result.output or "Cache" in result.output


class TestCompletionShowCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_show_does_not_crash(self):
        # May fail to generate script if promptgenie isn't on PATH but shouldn't crash
        result = self.runner.invoke(cli, ["completion", "show", "zsh"])
        assert result.exit_code in (0, 2)  # 0 = script generated, 2 = can't find promptgenie
