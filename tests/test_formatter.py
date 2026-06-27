"""Tests for the prompt/spec formatter engine and the ``promptgenie fmt`` command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.formatter import (
    CANONICAL_SPEC_KEYS,
    detect_file_type,
    format_text,
)

# ---------------------------------------------------------------------------
# Engine — Markdown
# ---------------------------------------------------------------------------


class TestMarkdownEngine:
    def test_trailing_whitespace_trimmed(self):
        r = format_text("hello   \nworld\t\n", file_type="markdown")
        assert r.formatted_text == "hello\nworld\n"
        assert any(x.name == "trim-trailing-ws" for x in r.rules)

    def test_blank_lines_collapsed(self):
        r = format_text("a\n\n\n\n\nb\n", file_type="markdown")
        assert r.formatted_text == "a\n\nb\n"
        assert any(x.name == "collapse-blank-lines" for x in r.rules)

    def test_single_final_newline_added(self):
        r = format_text("a\nb", file_type="markdown")
        assert r.formatted_text == "a\nb\n"
        assert any(x.name == "final-newline" for x in r.rules)

    def test_trailing_blank_lines_stripped(self):
        r = format_text("a\n\n\n", file_type="markdown")
        assert r.formatted_text == "a\n"

    def test_leading_blank_lines_stripped(self):
        r = format_text("\n\n# Title\nbody\n", file_type="markdown")
        assert r.formatted_text == "# Title\n\nbody\n"

    def test_heading_normalised(self):
        r = format_text("#  Title  ##\nbody\n", file_type="markdown")
        assert r.formatted_text == "# Title\n\nbody\n"
        assert any(x.name == "normalize-heading" for x in r.rules)

    def test_blank_line_padded_around_heading(self):
        r = format_text("intro\n## Section\nbody\n", file_type="markdown")
        assert r.formatted_text == "intro\n\n## Section\n\nbody\n"
        assert any(x.name == "blank-around-heading" for x in r.rules)

    def test_non_heading_hash_left_alone(self):
        # CommonMark: '#text' (no space) is a paragraph, not a heading.
        r = format_text("#notaheading\n", file_type="markdown")
        assert r.formatted_text == "#notaheading\n"
        assert not any(x.name == "normalize-heading" for x in r.rules)

    def test_code_fence_preserved_byte_for_byte(self):
        text = "intro\n\n```\ndef f():  \n    return 1   \n```\n"
        r = format_text(text, file_type="markdown")
        # Trailing whitespace inside the fence must survive untouched.
        assert "def f():  \n" in r.formatted_text
        assert "    return 1   \n" in r.formatted_text

    def test_blank_lines_inside_fence_preserved(self):
        text = "```\na\n\n\n\nb\n```\n"
        r = format_text(text, file_type="markdown")
        assert r.formatted_text == text
        assert not r.changed

    def test_already_formatted_is_unchanged(self):
        text = "# Title\n\nbody\n"
        r = format_text(text, file_type="markdown")
        assert not r.changed
        assert r.rules == []

    def test_idempotent(self):
        text = "#  Messy ##\n\n\n\nbody  \n##Sub\n```\nx   \n```\ntail"
        once = format_text(text, file_type="markdown").formatted_text
        twice = format_text(once, file_type="markdown")
        assert twice.formatted_text == once
        assert not twice.changed

    def test_empty_input(self):
        r = format_text("", file_type="markdown")
        assert r.formatted_text == ""
        assert not r.changed


# ---------------------------------------------------------------------------
# Engine — YAML
# ---------------------------------------------------------------------------


class TestYamlEngine:
    def test_keys_sorted_to_canonical_order(self):
        r = format_text("name: x\nversion: 1\ntarget: claude\n", file_type="yaml")
        lines = [ln.split(":")[0] for ln in r.formatted_text.strip().split("\n")]
        assert lines == ["version", "name", "target"]
        assert any(x.name == "sort-keys" for x in r.rules)

    def test_nested_run_keys_sorted(self):
        text = "name: x\nversion: 1\ntarget: claude\nrun:\n  timeout: 5\n  stream: true\n"
        r = format_text(text, file_type="yaml")
        body = r.formatted_text
        assert body.index("stream") < body.index("timeout")

    def test_unknown_keys_kept_after_known(self):
        text = "zeta: 1\nversion: 1\nname: x\ntarget: c\nalpha: 2\n"
        r = format_text(text, file_type="yaml")
        keys = [ln.split(":")[0] for ln in r.formatted_text.strip().split("\n")]
        assert keys[:3] == ["version", "name", "target"]
        # Extra keys retain their original relative order (zeta before alpha).
        assert keys.index("zeta") < keys.index("alpha")

    def test_comments_preserve_key_order_without_ruamel(self):
        # With a comment and no ruamel, keys must NOT be reordered (comment-safe).
        text = "name: x  # the name\nversion: 1\ntarget: claude\n"
        r = format_text(text, file_type="yaml")
        assert "# the name" in r.formatted_text
        keys = [ln.split(":")[0].strip() for ln in r.formatted_text.strip().split("\n")]
        assert keys[0] == "name"  # original order kept
        assert not any(x.name == "sort-keys" for x in r.rules)

    def test_yaml_trailing_whitespace_trimmed(self):
        r = format_text("version: 1   \nname: x\ntarget: c\n", file_type="yaml")
        assert "version: 1\n" in r.formatted_text
        assert any(x.name == "trim-trailing-ws" for x in r.rules)

    def test_invalid_yaml_only_whitespace_normalised(self):
        text = "this: : : not valid yaml   \n\n\n"
        r = format_text(text, file_type="yaml")
        # No crash; trailing whitespace/newlines cleaned, no reorder attempted.
        assert r.formatted_text == "this: : : not valid yaml\n"

    def test_yaml_idempotent(self):
        text = "name: x\nversion: 1\ntarget: claude\nrun:\n  timeout: 5\n  stream: true\n"
        once = format_text(text, file_type="yaml").formatted_text
        twice = format_text(once, file_type="yaml")
        assert twice.formatted_text == once
        assert not twice.changed


# ---------------------------------------------------------------------------
# File-type detection
# ---------------------------------------------------------------------------


class TestDetect:
    def test_markdown_exts(self):
        assert detect_file_type("a.md") == "markdown"
        assert detect_file_type("a.markdown") == "markdown"

    def test_yaml_exts(self):
        assert detect_file_type("a.yaml") == "yaml"
        assert detect_file_type("spec.yml") == "yaml"

    def test_stdin_and_unknown_default_markdown(self):
        assert detect_file_type("-") == "markdown"
        assert detect_file_type("notes.txt") == "markdown"

    def test_canonical_keys_match_spec_fields(self):
        # Guardrail: the canonical order must start with the required fields.
        assert CANONICAL_SPEC_KEYS[:3] == ("version", "name", "target")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestFmtCommand:
    def test_stdin_formats_to_stdout(self):
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", "-"], input="#  Hi \nyo   \n\n\n\nbye")
        assert res.exit_code == 0
        assert res.output == "# Hi\n\nyo\n\nbye\n"

    def test_check_exits_1_when_changes_needed(self, tmp_path: Path):
        f = tmp_path / "a.md"
        f.write_text("#  Title \nbody  \n", encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", "--check", str(f)])
        assert res.exit_code == 1
        # --check must not modify the file.
        assert f.read_text(encoding="utf-8") == "#  Title \nbody  \n"

    def test_check_exits_0_when_clean(self, tmp_path: Path):
        f = tmp_path / "a.md"
        f.write_text("# Title\n\nbody\n", encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", "--check", str(f)])
        assert res.exit_code == 0

    def test_in_place_write(self, tmp_path: Path):
        f = tmp_path / "a.md"
        f.write_text("#  Title \n\n\n\nbody  \n", encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", str(f)])
        assert res.exit_code == 0
        assert f.read_text(encoding="utf-8") == "# Title\n\nbody\n"

    def test_diff_does_not_write(self, tmp_path: Path):
        f = tmp_path / "a.md"
        original = "#  Title \nbody  \n"
        f.write_text(original, encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", "--diff", str(f)])
        assert res.exit_code == 0
        assert "# Title" in res.output
        assert "@@" in res.output
        assert f.read_text(encoding="utf-8") == original

    def test_json_report(self, tmp_path: Path):
        f = tmp_path / "s.yaml"
        f.write_text("name: x\nversion: 1\ntarget: c\n", encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", "--check", "--format", "json", str(f)])
        assert res.exit_code == 1
        data = json.loads(res.output)
        assert data["schema_version"] == "1.0"
        assert data["changed_count"] == 1
        assert data["files"][0]["file_type"] == "yaml"
        assert any(r["name"] == "sort-keys" for r in data["files"][0]["rules"])

    def test_directory_expansion(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("# A\nbody  \n", encoding="utf-8")
        (tmp_path / "b.yaml").write_text("name: x\nversion: 1\ntarget: c\n", encoding="utf-8")
        (tmp_path / "ignore.txt").write_text("not touched   \n", encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", "--check", str(tmp_path)])
        assert res.exit_code == 1
        # The .txt file is not a recognised prompt/spec extension and is skipped.
        assert (tmp_path / "ignore.txt").read_text(encoding="utf-8") == "not touched   \n"

    def test_lang_override_forces_yaml(self):
        runner = CliRunner()
        # Stdin defaults to markdown; --lang yaml forces key sorting.
        res = runner.invoke(
            cli,
            ["fmt", "--lang", "yaml", "-"],
            input="name: x\nversion: 1\ntarget: c\n",
        )
        assert res.exit_code == 0
        assert res.output.startswith("version: 1")

    def test_already_clean_directory_exit_0(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("# A\n\nbody\n", encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", str(tmp_path)])
        assert res.exit_code == 0

    def test_unreadable_path_exits_usage(self, tmp_path: Path):
        runner = CliRunner()
        res = runner.invoke(cli, ["fmt", str(tmp_path / "does-not-exist.md")])
        assert res.exit_code == 2
