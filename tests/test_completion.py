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

    def test_read_cache_corrupt_returns_none(self, tmp_path, monkeypatch):
        import promptgenie.commands.completion as comp

        bad = tmp_path / "completions.json"
        bad.write_text("{ not valid json ]", encoding="utf-8")
        monkeypatch.setattr(comp, "_CACHE_FILE", bad)
        assert _read_cache() is None  # JSON error is swallowed

    def test_write_cache_oserror_is_non_fatal(self, tmp_path, monkeypatch):
        import promptgenie.commands.completion as comp

        # Point the cache dir at an existing *file* so mkdir() raises OSError.
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        monkeypatch.setattr(comp, "_CACHE_DIR", blocker)
        monkeypatch.setattr(comp, "_CACHE_FILE", blocker / "completions.json")
        _write_cache({"targets": []})  # must not raise


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


class TestCompletionInstallCommand:
    """Exercise the install command end-to-end in a fully sandboxed HOME/cache."""

    def setup_method(self):
        self.runner = CliRunner()

    def _sandbox(self, tmp_path, monkeypatch):
        import promptgenie.commands.completion as comp

        monkeypatch.setenv("HOME", str(tmp_path))  # redirect ~/.zshrc, ~/.bashrc, etc.
        monkeypatch.setattr(comp, "_CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(comp, "_CACHE_FILE", tmp_path / "cache" / "completions.json")

    def test_install_zsh_no_rc_writes_completion_file(self, tmp_path, monkeypatch):
        self._sandbox(tmp_path, monkeypatch)
        comp_dir = tmp_path / "comp"
        res = self.runner.invoke(
            cli, ["completion", "install", "zsh", "--dir", str(comp_dir), "--no-rc"]
        )
        assert res.exit_code == 0
        assert (comp_dir / "_promptgenie").exists()
        # --no-rc means no RC file was touched.
        assert not (tmp_path / ".zshrc").exists()

    def test_install_bash_appends_rc_then_skips_on_repeat(self, tmp_path, monkeypatch):
        self._sandbox(tmp_path, monkeypatch)
        comp_dir = tmp_path / "comp"
        first = self.runner.invoke(cli, ["completion", "install", "bash", "--dir", str(comp_dir)])
        assert first.exit_code == 0
        rc = tmp_path / ".bashrc"
        assert rc.exists()
        assert "PromptGenie shell completion" in rc.read_text()
        before = rc.read_text()
        # Second install should detect the existing snippet and not duplicate it.
        second = self.runner.invoke(cli, ["completion", "install", "bash", "--dir", str(comp_dir)])
        assert second.exit_code == 0
        assert rc.read_text() == before  # idempotent

    def test_install_fish_auto_load_branch(self, tmp_path, monkeypatch):
        self._sandbox(tmp_path, monkeypatch)
        comp_dir = tmp_path / "comp"
        res = self.runner.invoke(cli, ["completion", "install", "fish", "--dir", str(comp_dir)])
        assert res.exit_code == 0
        # fish never writes an RC snippet (auto-loaded from the completions dir).
        assert "fish" in res.output.lower()
