"""Tests for promptgenie.core.linter."""

import pytest
from promptgenie.core.linter import lint, LintResult, LintIssue


GOOD_PROMPT = """# Prompt for Claude Code

## Objective
Refactor the authentication module to use JWT tokens.

## Scope
Work only within src/auth/ and src/middleware/auth.py.

## Constraints
Do not install packages without approval.

## Forbidden Actions
Do not push to any live environment.
Do not modify files outside scope.

## Stop Conditions
Stop and ask for approval if:
- A new dependency would be added
- Tests fail

## Output Format
Show diffs for each changed file. Run tests and report results.

## Acceptance Criteria
Done when all auth routes use JWT and tests pass.
"""


class TestLintReturnsResult:
    def test_returns_lint_result(self):
        result = lint(GOOD_PROMPT)
        assert isinstance(result, LintResult)

    def test_score_is_int_in_range(self):
        result = lint(GOOD_PROMPT)
        assert 0 <= result.score <= 100

    def test_good_prompt_has_no_high_issues(self):
        result = lint(GOOD_PROMPT)
        assert result.by_severity("HIGH") == []


class TestVagueVerbDetection:
    def test_detects_help(self):
        result = lint("help me with something in the codebase")
        codes = [i.code for i in result.issues]
        assert "TASK_001" in codes

    def test_detects_fix(self):
        result = lint("fix the whole app and make it better")
        codes = [i.code for i in result.issues]
        assert "TASK_001" in codes

    def test_clean_verb_no_false_positive(self):
        result = lint("Refactor the auth module to use JWT.")
        codes = [i.code for i in result.issues]
        assert "TASK_001" not in codes


class TestMissingTargetDetection:
    def test_detects_missing_target(self):
        result = lint("Refactor the auth module to use JWT.")
        codes = [i.code for i in result.issues]
        assert "TASK_003" in codes

    def test_no_missing_target_when_claude_present(self):
        result = lint("Refactor the auth module using Claude Code.")
        codes = [i.code for i in result.issues]
        assert "TASK_003" not in codes


class TestBroadScopeDetection:
    def test_detects_whole_app(self):
        result = lint("Refactor the whole app using Claude Code.")
        codes = [i.code for i in result.issues]
        assert "TASK_004" in codes

    def test_detects_entire_codebase(self):
        result = lint("Review the entire codebase with Claude Code.")
        codes = [i.code for i in result.issues]
        assert "TASK_004" in codes


class TestAgenticRiskDetection:
    def test_detects_do_whatever_it_takes(self):
        result = lint("Do whatever it takes to fix it using Claude Code.")
        codes = [i.code for i in result.issues]
        assert "AGENT_001" in codes

    def test_detects_fix_everything(self):
        result = lint("Fix everything in the codebase using Claude Code.")
        codes = [i.code for i in result.issues]
        assert "AGENT_002" in codes

    def test_detects_deploy_to_production(self):
        result = lint("When done deploy to production using Claude Code.")
        codes = [i.code for i in result.issues]
        assert "AGENT_005" in codes

    def test_detects_drop_table(self):
        result = lint("Drop the database and recreate it using Claude Code.")
        codes = [i.code for i in result.issues]
        assert "AGENT_006" in codes


class TestMissingStructure:
    def test_flags_missing_stop_conditions_for_agentic(self):
        prompt = "Refactor auth using Claude Code. Work in src/auth/."
        result = lint(prompt)
        codes = [i.code for i in result.issues]
        assert "STRUCT_001" in codes

    def test_flags_missing_output_format_for_agentic(self):
        prompt = "Refactor auth using Claude Code. Work in src/auth/."
        result = lint(prompt)
        codes = [i.code for i in result.issues]
        assert "STRUCT_004" in codes


class TestSeverityFiltering:
    def test_by_severity_returns_correct_subset(self):
        result = lint("help me fix everything in the whole app")
        high = result.by_severity("HIGH")
        assert all(i.severity == "HIGH" for i in high)

    def test_score_decreases_with_issues(self):
        good = lint(GOOD_PROMPT)
        bad = lint("help me fix the whole app and deploy to production")
        assert good.score > bad.score
