"""Tests for promptgenie.core.adapter."""

import pytest
from pathlib import Path
from promptgenie.core.adapter import adapt, AdaptResult


AGENTIC_PROMPT = """\
# Prompt for Claude Code

## Objective
Refactor the auth module to use JWT.

## Scope
Work only within src/auth/.

## Constraints
Do not install packages without approval.

## Stop Conditions
Stop and ask for approval if tests fail.

## Forbidden Actions
Do not deploy to production.
Do not modify files outside scope.

## Output Format
Show diffs. Run tests.

## Acceptance Criteria
Done when tests pass.
"""


@pytest.fixture
def agentic_file(tmp_path):
    f = tmp_path / "agentic.md"
    f.write_text(AGENTIC_PROMPT)
    return str(f)


class TestAdaptReturnsResult:
    def test_returns_adapt_result(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert isinstance(result, AdaptResult)

    def test_adapted_text_is_string(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert isinstance(result.adapted_text, str)
        assert len(result.adapted_text) > 0

    def test_change_log_is_populated(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert len(result.changes) > 0


class TestAgenticToAgenticAdaptation:
    def test_cursor_keeps_stop_conditions(self, agentic_file):
        """Agentic → Agentic should preserve all safety sections."""
        result = adapt(agentic_file, "claude-code", "cursor")
        assert "Stop" in result.adapted_text

    def test_cursor_keeps_scope(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert "Scope" in result.adapted_text

    def test_cursor_keeps_forbidden_actions(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert "Forbidden" in result.adapted_text

    def test_header_updated_to_cursor(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert "Cursor" in result.adapted_text


class TestAgenticToGeneralAdaptation:
    def test_chatgpt_drops_stop_conditions(self, agentic_file):
        """Agentic → General (chatgpt) should drop agentic safety sections."""
        result = adapt(agentic_file, "claude-code", "chatgpt")
        dropped = [c for c in result.changes if c.action == "dropped"]
        dropped_names = [c.name.lower() for c in dropped]
        assert any("stop" in n for n in dropped_names)

    def test_chatgpt_drops_scope(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "chatgpt")
        dropped = [c.name.lower() for c in result.changes if c.action == "dropped"]
        assert any("scope" in n for n in dropped)

    def test_chatgpt_issues_warning(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "chatgpt")
        assert len(result.warnings) > 0

    def test_chatgpt_keeps_objective(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "chatgpt")
        assert "Objective" in result.adapted_text

    def test_chatgpt_keeps_output_format(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "chatgpt")
        assert "Output" in result.adapted_text

    def test_chatgpt_has_fewer_tokens_than_source(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "chatgpt")
        assert result.adapted_tokens < result.source_tokens


class TestTokenAndScoreSummary:
    def test_source_tokens_positive(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert result.source_tokens > 0

    def test_adapted_tokens_positive(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert result.adapted_tokens > 0

    def test_source_score_has_total(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert "total" in result.source_score

    def test_adapted_score_has_total(self, agentic_file):
        result = adapt(agentic_file, "claude-code", "cursor")
        assert "total" in result.adapted_score
