"""Tests for promptgenie/core/fileio.py — safe file I/O helpers."""

from pathlib import Path

import pytest
import yaml

from promptgenie.core.fileio import (
    MAX_PROMPT_BYTES,
    MAX_YAML_BYTES,
    FileExistsProtectedError,
    FileTooLargeError,
    safe_read_text,
    safe_read_yaml,
    safe_write_text,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# safe_read_text
# ---------------------------------------------------------------------------


class TestSafeReadText:
    def test_reads_utf8_content(self, tmp_path):
        p = tmp_path / "hello.md"
        _write(p, "# Hello\nWorld 🌍")
        assert safe_read_text(p) == "# Hello\nWorld 🌍"

    def test_accepts_string_path(self, tmp_path):
        p = tmp_path / "f.txt"
        _write(p, "content")
        assert safe_read_text(str(p)) == "content"

    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            safe_read_text(tmp_path / "nonexistent.txt")

    def test_raises_file_too_large(self, tmp_path):
        p = tmp_path / "big.txt"
        p.write_bytes(b"x" * (MAX_PROMPT_BYTES + 1))
        with pytest.raises(FileTooLargeError) as exc_info:
            safe_read_text(p)
        assert exc_info.value.path == p
        assert exc_info.value.size == MAX_PROMPT_BYTES + 1
        assert exc_info.value.limit == MAX_PROMPT_BYTES

    def test_exactly_at_limit_is_allowed(self, tmp_path):
        p = tmp_path / "exact.txt"
        p.write_bytes(b"a" * MAX_PROMPT_BYTES)
        result = safe_read_text(p)
        assert len(result) == MAX_PROMPT_BYTES

    def test_one_byte_over_limit_is_rejected(self, tmp_path):
        p = tmp_path / "over.txt"
        p.write_bytes(b"a" * (MAX_PROMPT_BYTES + 1))
        with pytest.raises(FileTooLargeError):
            safe_read_text(p)

    def test_custom_max_bytes(self, tmp_path):
        p = tmp_path / "small.txt"
        _write(p, "hello world")  # 11 bytes
        with pytest.raises(FileTooLargeError):
            safe_read_text(p, max_bytes=5)

    def test_error_message_includes_path_and_sizes(self, tmp_path):
        p = tmp_path / "big.txt"
        p.write_bytes(b"x" * (MAX_PROMPT_BYTES + 100))
        with pytest.raises(FileTooLargeError) as exc_info:
            safe_read_text(p)
        msg = str(exc_info.value)
        assert str(p) in msg or p.name in msg
        assert f"{MAX_PROMPT_BYTES:,}" in msg


# ---------------------------------------------------------------------------
# safe_read_yaml
# ---------------------------------------------------------------------------


class TestSafeReadYaml:
    def test_parses_mapping(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        _write(p, "name: test\nvalue: 42\n")
        result = safe_read_yaml(p)
        assert result == {"name": "test", "value": 42}

    def test_parses_list(self, tmp_path):
        p = tmp_path / "list.yaml"
        _write(p, "- a\n- b\n- c\n")
        assert safe_read_yaml(p) == ["a", "b", "c"]

    def test_empty_file_returns_none(self, tmp_path):
        p = tmp_path / "empty.yaml"
        _write(p, "")
        assert safe_read_yaml(p) is None

    def test_uses_yaml_size_limit_by_default(self, tmp_path):
        p = tmp_path / "big.yaml"
        p.write_bytes(b"x: " + b"y" * (MAX_YAML_BYTES + 1))
        with pytest.raises(FileTooLargeError):
            safe_read_yaml(p)

    def test_yaml_limit_smaller_than_prompt_limit(self):
        assert MAX_YAML_BYTES < MAX_PROMPT_BYTES

    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            safe_read_yaml(tmp_path / "missing.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        _write(p, "key: [unclosed")
        with pytest.raises(yaml.YAMLError):
            safe_read_yaml(p)


# ---------------------------------------------------------------------------
# safe_write_text
# ---------------------------------------------------------------------------


class TestSafeWriteText:
    def test_creates_new_file(self, tmp_path):
        p = tmp_path / "out.txt"
        safe_write_text(p, "hello")
        assert p.read_text(encoding="utf-8") == "hello"

    def test_creates_parent_directories(self, tmp_path):
        p = tmp_path / "a" / "b" / "c" / "out.txt"
        safe_write_text(p, "nested")
        assert p.exists()
        assert p.read_text(encoding="utf-8") == "nested"

    def test_writes_utf8_content(self, tmp_path):
        p = tmp_path / "utf8.txt"
        content = "Hello 🌍 — café"
        safe_write_text(p, content)
        assert p.read_text(encoding="utf-8") == content

    def test_raises_if_exists_without_force(self, tmp_path):
        p = tmp_path / "existing.txt"
        _write(p, "original")
        with pytest.raises(FileExistsProtectedError) as exc_info:
            safe_write_text(p, "new content")
        assert exc_info.value.path == p
        # Original file must be untouched
        assert p.read_text(encoding="utf-8") == "original"

    def test_overwrites_with_force(self, tmp_path):
        p = tmp_path / "existing.txt"
        _write(p, "original")
        safe_write_text(p, "replaced", force=True)
        assert p.read_text(encoding="utf-8") == "replaced"

    def test_error_message_mentions_force(self, tmp_path):
        p = tmp_path / "f.txt"
        _write(p, "x")
        with pytest.raises(FileExistsProtectedError) as exc_info:
            safe_write_text(p, "y")
        assert "--force" in str(exc_info.value)

    def test_atomic_write_no_temp_file_left_on_success(self, tmp_path):
        p = tmp_path / "out.txt"
        safe_write_text(p, "content")
        tmp_files = list(tmp_path.glob(".promptgenie_tmp_*"))
        assert tmp_files == [], f"Temp files left behind: {tmp_files}"

    def test_accepts_string_path(self, tmp_path):
        p = str(tmp_path / "str.txt")
        safe_write_text(p, "via string")
        assert Path(p).read_text(encoding="utf-8") == "via string"

    def test_overwrites_existing_when_same_dest_as_source(self, tmp_path):
        """Simulates pack inject where dest == source (always force)."""
        p = tmp_path / "prompt.md"
        _write(p, "original")
        # force=True should succeed
        safe_write_text(p, "updated", force=True)
        assert p.read_text(encoding="utf-8") == "updated"


# ---------------------------------------------------------------------------
# Integration: safe_write_text + safe_read_text round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_write_then_read(self, tmp_path):
        p = tmp_path / "round.md"
        content = "## Objective\nDo the thing.\n\n## Stop Conditions\nStop if it breaks.\n"
        safe_write_text(p, content)
        assert safe_read_text(p) == content

    def test_write_then_read_yaml(self, tmp_path):
        p = tmp_path / "config.yaml"
        data = {
            "scanner": {"disabled_rules": ["SEC_001"]},
            "linter": {"custom_vague_verbs": ["tidy"]},
        }
        safe_write_text(p, yaml.dump(data))
        result = safe_read_yaml(p)
        assert result == data
