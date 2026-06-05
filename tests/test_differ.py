"""Tests for promptgenie.core.differ."""

import pytest

from promptgenie.core.differ import DiffResult, diff_prompts

V1 = """\
# Prompt for Claude Code

## Objective
Refactor auth to use JWT.

## Output Format
Show diffs.
"""

V2 = """\
# Prompt for Claude Code

## Objective
Refactor the auth module to replace session-based auth with JWT tokens.

## Scope
Work only within src/auth/ and src/middleware/auth.py.

## Stop Conditions
Stop and ask for approval if tests fail.

## Output Format
Show diffs for each changed file. Run tests and report results.

## Acceptance Criteria
Done when all auth routes use JWT and tests pass.
"""


@pytest.fixture
def v1_file(tmp_path):
    f = tmp_path / "v1.md"
    f.write_text(V1)
    return str(f)


@pytest.fixture
def v2_file(tmp_path):
    f = tmp_path / "v2.md"
    f.write_text(V2)
    return str(f)


class TestDiffResult:
    def test_returns_diff_result(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file)
        assert isinstance(result, DiffResult)

    def test_token_delta_is_positive(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file)
        assert result.token_delta > 0

    def test_a_has_fewer_tokens_than_b(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file)
        assert result.a_tokens < result.b_tokens

    def test_score_delta_present(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file)
        assert isinstance(result.score_delta, int)

    def test_b_has_higher_score_than_a(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file)
        assert result.b_score["total"] >= result.a_score["total"]


class TestSectionDeltas:
    def test_detects_added_sections(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file)
        added = [d for d in result.section_deltas if d.status == "added"]
        names = [d.name for d in added]
        assert "Scope" in names
        assert "Stop Conditions" in names
        assert "Acceptance Criteria" in names

    def test_detects_changed_sections(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file)
        changed = [d for d in result.section_deltas if d.status == "changed"]
        names = [d.name for d in changed]
        assert "Objective" in names

    def test_detects_unchanged_sections(self, v1_file, v2_file):
        # Same file vs itself
        result = diff_prompts(v1_file, v1_file)
        statuses = {d.status for d in result.section_deltas if d.name != "__preamble__"}
        assert statuses <= {"unchanged"}


class TestLintDelta:
    def test_v1_has_more_lint_issues_than_v2(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file, target="claude-code")
        assert len(result.a_lint.issues) >= len(result.b_lint.issues)

    def test_resolved_issues_from_a_not_in_b(self, v1_file, v2_file):
        result = diff_prompts(v1_file, v2_file, target="claude-code")
        b_codes = {i.code for i in result.b_lint.issues}
        for issue in result.resolved_lint_issues:
            assert issue.code not in b_codes


class TestIdenticalFiles:
    def test_zero_delta_for_identical_files(self, v1_file):
        result = diff_prompts(v1_file, v1_file)
        assert result.token_delta == 0
        assert result.score_delta == 0
        assert result.lint_delta == 0
