"""Tests for extended differ — side-by-side, JSON/YAML/Markdown output."""

from __future__ import annotations

import json

import yaml

from promptgenie.core.differ import (
    DiffResult,
    SideBySideRow,
    build_side_by_side,
    diff_to_json,
    diff_to_markdown,
    diff_to_yaml,
)
from promptgenie.core.linter import lint
from promptgenie.core.scanner import scan

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROMPT_A = """# Prompt for Claude Code

## Objective
Refactor the authentication module.

## Scope
Work only within src/auth/.

## Stop Conditions
Stop and ask before deploying.
"""

PROMPT_B = """# Prompt for Claude Code

## Objective
Refactor the authentication module to use JWT tokens.

## Scope
Work only within src/auth/ and src/middleware/.

## Output Format
Show diffs for each changed file.

## Stop Conditions
Stop and ask before deploying.
"""


def _make_result(a_text: str, b_text: str) -> DiffResult:
    import difflib

    from promptgenie.core.differ import _section_deltas
    from promptgenie.core.generator import estimate_tokens, score_prompt

    profile = {"name": "claude", "required_sections": [], "forbidden_patterns": []}
    a_tokens = estimate_tokens(a_text)
    b_tokens = estimate_tokens(b_text)
    a_score = score_prompt(a_text, profile)
    b_score = score_prompt(b_text, profile)
    a_lint = lint(a_text)
    b_lint = lint(b_text)
    a_scan = scan(a_text)
    b_scan = scan(b_text)
    unified = list(
        difflib.unified_diff(
            a_text.splitlines(keepends=True),
            b_text.splitlines(keepends=True),
            fromfile="a.md",
            tofile="b.md",
            lineterm="",
        )
    )
    deltas = _section_deltas(a_text, b_text)
    return DiffResult(
        a_text=a_text,
        b_text=b_text,
        a_path="a.md",
        b_path="b.md",
        a_tokens=a_tokens,
        b_tokens=b_tokens,
        a_score=a_score,
        b_score=b_score,
        a_lint=a_lint,
        b_lint=b_lint,
        a_scan=a_scan,
        b_scan=b_scan,
        unified_diff=unified,
        section_deltas=deltas,
    )


# ---------------------------------------------------------------------------
# diff_to_json
# ---------------------------------------------------------------------------


class TestDiffToJson:
    def test_returns_valid_json(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        output = diff_to_json(result)
        data = json.loads(output)
        assert isinstance(data, dict)

    def test_schema_version(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        data = json.loads(diff_to_json(result))
        assert data["schema_version"] == "1.0"

    def test_command_field(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        data = json.loads(diff_to_json(result))
        assert data["command"] == "diff"

    def test_summary_keys(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        data = json.loads(diff_to_json(result))
        assert "tokens" in data["summary"]
        assert "score" in data["summary"]
        assert "lint_issues" in data["summary"]
        assert "security_findings" in data["summary"]

    def test_token_delta_correct(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        data = json.loads(diff_to_json(result))
        delta = data["summary"]["tokens"]["delta"]
        assert delta == result.b_tokens - result.a_tokens

    def test_sections_list(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        data = json.loads(diff_to_json(result))
        assert isinstance(data["sections"], list)
        # Output Format section was added
        added = [s for s in data["sections"] if s["status"] == "added"]
        assert any(s["name"] == "Output Format" for s in added)

    def test_paths(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        data = json.loads(diff_to_json(result))
        assert data["a"] == "a.md"
        assert data["b"] == "b.md"


# ---------------------------------------------------------------------------
# diff_to_yaml
# ---------------------------------------------------------------------------


class TestDiffToYaml:
    def test_returns_valid_yaml(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        output = diff_to_yaml(result)
        data = yaml.safe_load(output)
        assert isinstance(data, dict)

    def test_schema_version_present(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        data = yaml.safe_load(diff_to_yaml(result))
        assert data["schema_version"] == "1.0"

    def test_yaml_and_json_equivalent(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        json_data = json.loads(diff_to_json(result))
        yaml_data = yaml.safe_load(diff_to_yaml(result))
        assert json_data["summary"]["tokens"]["delta"] == yaml_data["summary"]["tokens"]["delta"]
        assert json_data["schema_version"] == yaml_data["schema_version"]


# ---------------------------------------------------------------------------
# diff_to_markdown
# ---------------------------------------------------------------------------


class TestDiffToMarkdown:
    def test_returns_string(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        md = diff_to_markdown(result)
        assert isinstance(md, str)

    def test_contains_heading(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        md = diff_to_markdown(result)
        assert "## Diff:" in md

    def test_contains_summary_table(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        md = diff_to_markdown(result)
        assert "| Tokens |" in md
        assert "| Quality score |" in md

    def test_added_section_shown(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        md = diff_to_markdown(result)
        assert "Output Format" in md
        assert "ADDED" in md

    def test_no_lint_issues_section_when_clean(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        md = diff_to_markdown(result)
        # Only include section if there are new/resolved issues
        new_issues = result.new_lint_issues
        if not new_issues:
            assert "### New Lint Issues" not in md


# ---------------------------------------------------------------------------
# build_side_by_side
# ---------------------------------------------------------------------------


class TestBuildSideBySide:
    def test_returns_list_of_rows(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        rows = build_side_by_side(result)
        assert isinstance(rows, list)
        assert len(rows) > 0
        assert all(isinstance(r, SideBySideRow) for r in rows)

    def test_header_rows_present(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        rows = build_side_by_side(result)
        header_rows = [r for r in rows if r.status.startswith("header:")]
        assert len(header_rows) > 0

    def test_added_section_has_insert_rows(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        rows = build_side_by_side(result)
        # Output Format was added — its rows should have a_line="" and status="insert"
        insert_rows = [r for r in rows if r.status == "insert"]
        assert len(insert_rows) > 0

    def test_unchanged_rows_present(self):
        result = _make_result(PROMPT_A, PROMPT_B)
        rows = build_side_by_side(result)
        equal_rows = [r for r in rows if r.status == "equal"]
        assert len(equal_rows) > 0

    def test_identical_prompts_no_changes(self):
        result = _make_result(PROMPT_A, PROMPT_A)
        rows = build_side_by_side(result)
        # All non-header rows should be "equal"
        non_header = [r for r in rows if not r.status.startswith("header:")]
        for row in non_header:
            assert row.status == "equal"


# ---------------------------------------------------------------------------
# diff_to_json schema_version in formatters
# ---------------------------------------------------------------------------


class TestFormattersSchemaVersion:
    def test_lint_to_json_has_schema_version(self):
        from promptgenie.core.formatters import lint_to_json
        from promptgenie.core.linter import lint

        result = lint("Test prompt.")
        data = json.loads(lint_to_json(result, prompt_path="test.md"))
        assert data["schema_version"] == "1.0"

    def test_scan_to_json_has_schema_version(self):
        from promptgenie.core.formatters import scan_to_json
        from promptgenie.core.scanner import scan

        result = scan("Test prompt.")
        data = json.loads(scan_to_json(result, prompt_path="test.md"))
        assert data["schema_version"] == "1.0"

    def test_multi_scan_to_json_has_schema_version(self):
        from promptgenie.core.formatters import multi_scan_to_json
        from promptgenie.core.scanner import scan

        result = scan("Test prompt.")
        data = json.loads(multi_scan_to_json([("test.md", result)]))
        assert data["schema_version"] == "1.0"
