"""Tests for the native compression engine and the compress/optimize command."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.compressor import (
    AGGRESSIVE_TECHNIQUES,
    ALL_TECHNIQUES,
    DEFAULT_TECHNIQUES,
    UnknownTechniqueError,
    compress,
)

# ---------------------------------------------------------------------------
# Engine — default (safe) techniques
# ---------------------------------------------------------------------------

class TestDefaultTechniques:
    def test_trailing_whitespace_trimmed(self):
        result = compress("hello   \nworld\t\n")
        assert result.compressed_text == "hello\nworld\n"
        assert any(t.name == "trim-trailing-ws" for t in result.applied)

    def test_blank_lines_collapsed(self):
        result = compress("a\n\n\n\n\nb\n")
        assert result.compressed_text == "a\n\nb\n"
        assert any(t.name == "collapse-blank-lines" for t in result.applied)

    def test_single_blank_line_preserved(self):
        text = "a\n\nb\n"
        result = compress(text)
        assert result.compressed_text == text

    def test_whole_document_json_compacted(self):
        text = '{\n  "a": 1,\n  "b": [1, 2, 3]\n}'
        result = compress(text)
        assert result.compressed_text == '{"a":1,"b":[1,2,3]}'
        assert any(t.name == "json-compact" for t in result.applied)

    def test_fenced_json_compacted(self):
        text = '# Title\n\n```json\n{\n  "x": 1\n}\n```\n'
        result = compress(text)
        assert '```json\n{"x":1}\n```' in result.compressed_text

    def test_invalid_json_untouched(self):
        text = "{not valid json}"
        result = compress(text)
        assert result.compressed_text == text

    def test_tokens_reduced(self):
        text = "word   \n\n\n\n\nword\n"
        result = compress(text)
        assert result.tokens_after <= result.tokens_before

    def test_no_op_on_compact_text(self):
        text = "Already compact.\n"
        result = compress(text)
        assert not result.changed
        assert result.applied == []


# ---------------------------------------------------------------------------
# Engine — fence safety
# ---------------------------------------------------------------------------

class TestFenceSafety:
    def test_code_indentation_preserved(self):
        text = "Some prose   with   spaces\n\n```python\ndef f():\n    x  =  1\n    return  x\n```\n"
        result = compress(text, techniques=["collapse-spaces"])
        # Prose spaces squeezed, code block left intact.
        assert "Some prose with spaces" in result.compressed_text
        assert "    x  =  1" in result.compressed_text

    def test_roundtrip_join_is_lossless_for_noop(self):
        text = "a\n```\ncode  here\n```\nb\n"
        result = compress(text, techniques=["trim-trailing-ws"])
        assert result.compressed_text == text


# ---------------------------------------------------------------------------
# Engine — aggressive techniques
# ---------------------------------------------------------------------------

class TestAggressiveTechniques:
    def test_html_comments_stripped(self):
        text = "before <!-- secret note --> after\n"
        result = compress(text, techniques=["strip-html-comments"])
        assert "secret note" not in result.compressed_text

    def test_repeated_spaces_collapsed(self):
        result = compress("a     b     c\n", techniques=["collapse-spaces"])
        assert result.compressed_text == "a b c\n"

    def test_duplicate_log_lines_folded(self):
        text = "ERROR boom\nERROR boom\nERROR boom\nERROR boom\ndone\n"
        result = compress(text, techniques=["dedupe-log-lines"])
        assert "(×4)" in result.compressed_text
        assert "done" in result.compressed_text

    def test_two_duplicates_not_folded(self):
        text = "x\nx\ny\n"
        result = compress(text, techniques=["dedupe-log-lines"])
        assert result.compressed_text == text

    def test_aggressive_not_in_default_tier(self):
        for name in AGGRESSIVE_TECHNIQUES:
            assert name not in DEFAULT_TECHNIQUES


# ---------------------------------------------------------------------------
# Engine — budget + selection
# ---------------------------------------------------------------------------

class TestBudgetAndSelection:
    def test_max_tokens_enables_all_techniques(self):
        text = "a     b <!-- c -->   \n\n\n\nd\n"
        result = compress(text, max_tokens=1000)
        # budget comfortably met
        assert result.budget_met is True

    def test_budget_not_met_flagged(self):
        text = "word " * 200
        result = compress(text, max_tokens=1)
        assert result.budget_met is False

    def test_no_budget_leaves_budget_met_none(self):
        result = compress("hello\n")
        assert result.budget_met is None

    def test_unknown_technique_raises(self):
        with pytest.raises(UnknownTechniqueError):
            compress("x", techniques=["does-not-exist"])

    def test_explicit_selection_respects_canonical_order(self):
        result = compress("a   \n\n\n\nb\n", techniques=["collapse-blank-lines", "trim-trailing-ws"])
        names = [t.name for t in result.applied]
        assert names == [n for n in ALL_TECHNIQUES if n in names]

    def test_ratio_and_saved_consistent(self):
        result = compress("hello   \n\n\n\nworld\n")
        assert result.tokens_saved == result.tokens_before - result.tokens_after


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCompressCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def _file(self, content: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write(content)
        return tmp.name

    def test_compress_stdout(self):
        path = self._file("hi   \n\n\n\nthere\n")
        result = self.runner.invoke(cli, ["compress", path])
        assert result.exit_code == 0
        assert "hi\n\nthere" in result.stdout

    def test_optimize_alias_exists(self):
        path = self._file("hi   \n\n\n\nthere\n")
        result = self.runner.invoke(cli, ["optimize", path])
        assert result.exit_code == 0

    def test_json_format(self):
        path = self._file('{\n  "a": 1\n}')
        result = self.runner.invoke(cli, ["compress", path, "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["tokens_saved"] >= 0
        assert data["schema_version"] == "1.0"

    def test_out_file_written(self):
        path = self._file("a   \n\n\n\nb\n")
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "out.md")
            result = self.runner.invoke(cli, ["compress", path, "--out", out])
            assert result.exit_code == 0
            assert Path(out).read_text() == "a\n\nb\n"

    def test_dry_run_does_not_emit_compressed_text(self):
        path = self._file("a   \n\n\n\nb\n")
        result = self.runner.invoke(cli, ["compress", path, "--dry-run"])
        assert result.exit_code == 0
        assert result.stdout == ""  # summary goes to stderr

    def test_stdin(self):
        result = self.runner.invoke(cli, ["compress", "-"], input="x   \n\n\n\ny\n")
        assert result.exit_code == 0
        assert "x\n\ny" in result.stdout

    def test_max_tokens_budget_failure_exit_1(self):
        path = self._file("word " * 200)
        result = self.runner.invoke(cli, ["compress", path, "--max-tokens", "1", "--dry-run"])
        assert result.exit_code == 1

    def test_list_techniques(self):
        result = self.runner.invoke(cli, ["compress", "--list-techniques"])
        assert result.exit_code == 0
        assert "json-compact" in result.stderr

    def test_unknown_technique_exit_2(self):
        path = self._file("hello\n")
        result = self.runner.invoke(cli, ["compress", path, "--techniques", "nope"])
        assert result.exit_code == 2
