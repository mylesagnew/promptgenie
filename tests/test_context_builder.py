"""Tests for promptgenie.core.context_builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from promptgenie.core.context_builder import (
    ContextManifest,
    SourceEntry,
    _apply_strategy,
    _estimate_tokens,
    _gather_env,
    _gather_file,
    _gather_git,
    _is_ignored,
    _load_promptignore,
    build_context,
)
from promptgenie.core.errors import PromptGenieError
from promptgenie.core.spec import ContextSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(label: str, tokens: int = 10, mtime: float = 0.0,
                source_type: str = "file") -> SourceEntry:
    return SourceEntry(
        label=label, source_type=source_type,
        content="x" * (tokens * 4), sha256="abc",
        token_estimate=tokens, mtime=mtime,
    )


# ---------------------------------------------------------------------------
# _estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") >= 1

    def test_scales_with_length(self):
        short = _estimate_tokens("hello")
        long = _estimate_tokens("hello " * 100)
        assert long > short

    def test_rough_heuristic(self):
        # 400 chars → ~100 tokens
        assert _estimate_tokens("x" * 400) == 100


# ---------------------------------------------------------------------------
# .promptignore
# ---------------------------------------------------------------------------


class TestPromptIgnore:
    def test_empty_if_missing(self, tmp_path):
        patterns = _load_promptignore(tmp_path)
        assert patterns == []

    def test_loads_patterns(self, tmp_path):
        (tmp_path / ".promptignore").write_text("*.log\n# comment\n__pycache__/\n",
                                                 encoding="utf-8")
        patterns = _load_promptignore(tmp_path)
        assert "*.log" in patterns
        assert "# comment" not in patterns

    def test_is_ignored_by_extension(self, tmp_path):
        f = tmp_path / "app.log"
        f.touch()
        assert _is_ignored(f, ["*.log"], tmp_path)

    def test_is_not_ignored(self, tmp_path):
        f = tmp_path / "app.py"
        f.touch()
        assert not _is_ignored(f, ["*.log"], tmp_path)


# ---------------------------------------------------------------------------
# _gather_file
# ---------------------------------------------------------------------------


class TestGatherFile:
    def test_reads_file(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')", encoding="utf-8")
        entry = _gather_file(str(f), "", 0, tmp_path, [])
        assert entry is not None
        assert "print" in entry.content
        assert entry.sha256 != ""

    def test_returns_none_for_missing_file(self, tmp_path):
        assert _gather_file("nonexistent.py", "", 0, tmp_path, []) is None

    def test_respects_max_bytes(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_bytes(b"x" * 1000)
        entry = _gather_file(str(f), "", 100, tmp_path, [])
        assert entry is not None
        assert len(entry.content) <= 100

    def test_returns_none_when_ignored(self, tmp_path):
        f = tmp_path / "secret.log"
        f.write_text("secret", encoding="utf-8")
        assert _gather_file(str(f), "", 0, tmp_path, ["*.log"]) is None


# ---------------------------------------------------------------------------
# _gather_env
# ---------------------------------------------------------------------------


class TestGatherEnv:
    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello-env")
        entry = _gather_env("MY_VAR", "")
        assert entry is not None
        assert entry.content == "hello-env"

    def test_returns_none_for_missing_var(self):
        entry = _gather_env("DEFINITELY_NOT_SET_XYZ", "")
        assert entry is None


# ---------------------------------------------------------------------------
# _apply_strategy
# ---------------------------------------------------------------------------


class TestApplyStrategy:
    def test_manual_preserves_order(self):
        entries = [_make_entry("c"), _make_entry("a"), _make_entry("b")]
        result = _apply_strategy(entries, "manual")
        assert [e.label for e in result] == ["c", "a", "b"]

    def test_smallest_sorts_by_tokens(self):
        entries = [_make_entry("big", 100), _make_entry("small", 5), _make_entry("med", 20)]
        result = _apply_strategy(entries, "smallest")
        assert result[0].label == "small"
        assert result[-1].label == "big"

    def test_newest_sorts_by_mtime_desc(self):
        entries = [
            _make_entry("old", mtime=1.0),
            _make_entry("new", mtime=100.0),
            _make_entry("mid", mtime=50.0),
        ]
        result = _apply_strategy(entries, "newest")
        assert result[0].label == "new"

    def test_git_relevant_puts_git_first(self):
        entries = [
            _make_entry("file.py", source_type="file"),
            _make_entry("diff", source_type="git_diff"),
        ]
        result = _apply_strategy(entries, "git-relevant")
        assert result[0].source_type == "git_diff"

    def test_unknown_strategy_is_manual(self):
        entries = [_make_entry("x"), _make_entry("y")]
        result = _apply_strategy(entries, "nonexistent")
        assert [e.label for e in result] == ["x", "y"]


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_file_source(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')", encoding="utf-8")
        sources = [ContextSource(type="file", path=str(f))]
        manifest = build_context(sources, base_dir=tmp_path)
        assert "print" in manifest.text
        assert manifest.total_tokens > 0

    def test_glob_source(self, tmp_path):
        (tmp_path / "a.py").write_text("a = 1", encoding="utf-8")
        (tmp_path / "b.py").write_text("b = 2", encoding="utf-8")
        sources = [ContextSource(type="glob", pattern="*.py")]
        manifest = build_context(sources, base_dir=tmp_path)
        assert "a = 1" in manifest.text
        assert "b = 2" in manifest.text
        assert len(manifest.entries) == 2

    def test_env_source(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MY_CTX_VAR", "env-value")
        sources = [ContextSource(type="env", var="MY_CTX_VAR")]
        manifest = build_context(sources, base_dir=tmp_path)
        assert "env-value" in manifest.text

    def test_token_budget_trims_sources(self, tmp_path):
        big_text = "word " * 1000  # ~1000 tokens
        (tmp_path / "big.txt").write_text(big_text, encoding="utf-8")
        (tmp_path / "small.txt").write_text("tiny", encoding="utf-8")
        sources = [
            ContextSource(type="file", path="big.txt"),
            ContextSource(type="file", path="small.txt"),
        ]
        manifest = build_context(sources, max_tokens=10, strategy="smallest",
                                 base_dir=tmp_path)
        assert manifest.trimmed_count > 0

    def test_empty_sources(self, tmp_path):
        manifest = build_context([], base_dir=tmp_path)
        assert manifest.text == ""
        assert manifest.entries == []

    def test_url_blocked_by_default(self, tmp_path):
        sources = [ContextSource(type="url", url="http://example.com", policy_gated=True)]
        with pytest.raises(PromptGenieError):
            build_context(sources, base_dir=tmp_path, no_url=True)

    def test_manifest_has_sha256(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1", encoding="utf-8")
        sources = [ContextSource(type="file", path=str(f))]
        manifest = build_context(sources, base_dir=tmp_path)
        assert manifest.entries[0].sha256 != ""

    def test_source_header_in_text(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("def foo(): pass", encoding="utf-8")
        sources = [ContextSource(type="file", path=str(f))]
        manifest = build_context(sources, base_dir=tmp_path)
        assert "### [file]" in manifest.text
