"""Tests for core/tester.py — all assertion types (Wave 5 coverage)."""

import tempfile
from pathlib import Path

import pytest

from promptgenie.core.linter import LintResult
from promptgenie.core.scanner import ScanResult
from promptgenie.core.tester import (
    PromptTestAssertion,
    PromptTestCaseResult,
    PromptTestSuiteResult,
    _run_case,
    run_test_suite,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_suite_files(prompt_text: str, suite_yaml: str) -> tuple[Path, Path]:
    """Write a prompt file and a test-suite YAML to a temp dir, return (suite_path, prompt_path)."""
    tmp = Path(tempfile.mkdtemp())
    prompt_path = tmp / "prompt.md"
    prompt_path.write_text(prompt_text)
    suite_path = tmp / "suite.prompt-test.yaml"
    suite_path.write_text(suite_yaml)
    return suite_path, prompt_path


def _empty_results(prompt: str = "hello"):
    from promptgenie.core.generator import estimate_tokens, score_prompt

    lint_result = LintResult()
    scan_result = ScanResult()
    token_count = estimate_tokens(prompt)
    score = score_prompt(prompt, {"required_sections": [], "forbidden_patterns": []})
    return lint_result, scan_result, token_count, score


# ── _run_case assertion types ────────────────────────────────────────────────


class TestMustInclude:
    def test_passes_when_present(self):
        lint_r, scan_r, tok, score = _empty_results("hello world")
        case = {"name": "t", "must_include": ["hello"]}
        result = _run_case(case, "hello world", {}, lint_r, scan_r, tok, score)
        assert result.passed

    def test_fails_when_absent(self):
        lint_r, scan_r, tok, score = _empty_results("hello world")
        case = {"name": "t", "must_include": ["goodbye"]}
        result = _run_case(case, "hello world", {}, lint_r, scan_r, tok, score)
        assert not result.passed

    def test_case_insensitive(self):
        lint_r, scan_r, tok, score = _empty_results("HELLO WORLD")
        case = {"name": "t", "must_include": ["hello"]}
        result = _run_case(case, "HELLO WORLD", {}, lint_r, scan_r, tok, score)
        assert result.passed


class TestMustNotInclude:
    def test_passes_when_absent(self):
        lint_r, scan_r, tok, score = _empty_results("safe text")
        case = {"name": "t", "must_not_include": ["danger"]}
        result = _run_case(case, "safe text", {}, lint_r, scan_r, tok, score)
        assert result.passed

    def test_fails_when_present(self):
        lint_r, scan_r, tok, score = _empty_results("contains danger here")
        case = {"name": "t", "must_not_include": ["danger"]}
        result = _run_case(case, "contains danger here", {}, lint_r, scan_r, tok, score)
        assert not result.passed


class TestMinScore:
    def test_passes_above_threshold(self):
        lint_r, scan_r, tok, score = _empty_results()
        score = {"total": 85, "breakdown": {}}
        case = {"name": "t", "min_score": 80}
        result = _run_case(case, "text", {}, lint_r, scan_r, tok, score)
        assert result.passed

    def test_fails_below_threshold(self):
        lint_r, scan_r, tok, score = _empty_results()
        score = {"total": 50, "breakdown": {}}
        case = {"name": "t", "min_score": 80}
        result = _run_case(case, "text", {}, lint_r, scan_r, tok, score)
        assert not result.passed


class TestMaxTokens:
    def test_passes_under_limit(self):
        lint_r, scan_r, tok, score = _empty_results()
        case = {"name": "t", "max_tokens": 1000}
        result = _run_case(case, "short text", {}, lint_r, scan_r, 10, score)
        assert result.passed

    def test_fails_over_limit(self):
        lint_r, scan_r, tok, score = _empty_results()
        case = {"name": "t", "max_tokens": 5}
        result = _run_case(case, "text", {}, lint_r, scan_r, 100, score)
        assert not result.passed


class TestMaxLintSeverity:
    def test_passes_when_no_violations(self):
        from promptgenie.core.linter import LintIssue

        lint_r = LintResult(issues=[LintIssue(severity="LOW", code="X", message="m")])
        scan_r = ScanResult()
        score = {"total": 70, "breakdown": {}}
        case = {"name": "t", "max_lint_severity": "MEDIUM"}
        result = _run_case(case, "text", {}, lint_r, scan_r, 10, score)
        assert result.passed

    def test_fails_when_high_issue_present(self):
        from promptgenie.core.linter import LintIssue

        lint_r = LintResult(issues=[LintIssue(severity="HIGH", code="X", message="m")])
        scan_r = ScanResult()
        score = {"total": 70, "breakdown": {}}
        case = {"name": "t", "max_lint_severity": "MEDIUM"}
        result = _run_case(case, "text", {}, lint_r, scan_r, 10, score)
        assert not result.passed


class TestMaxSecurityRisk:
    def test_passes_when_no_violations(self):
        from promptgenie.core.scanner import SecurityFinding

        scan_r = ScanResult(findings=[SecurityFinding(risk="LOW", code="X", message="m")])
        lint_r = LintResult()
        score = {"total": 70, "breakdown": {}}
        case = {"name": "t", "max_security_risk": "MEDIUM"}
        result = _run_case(case, "text", {}, lint_r, scan_r, 10, score)
        assert result.passed

    def test_fails_when_high_finding_present(self):
        from promptgenie.core.scanner import SecurityFinding

        scan_r = ScanResult(findings=[SecurityFinding(risk="CRITICAL", code="X", message="m")])
        lint_r = LintResult()
        score = {"total": 70, "breakdown": {}}
        case = {"name": "t", "max_security_risk": "MEDIUM"}
        result = _run_case(case, "text", {}, lint_r, scan_r, 10, score)
        assert not result.passed


class TestRequiredSections:
    def test_passes_when_section_present(self):
        lint_r, scan_r, tok, score = _empty_results()
        prompt = "## Objective\nDo the thing."
        case = {"name": "t", "required_sections": ["Objective"]}
        result = _run_case(case, prompt, {}, lint_r, scan_r, tok, score)
        assert result.passed

    def test_fails_when_section_missing(self):
        lint_r, scan_r, tok, score = _empty_results()
        prompt = "Just some text with no sections."
        case = {"name": "t", "required_sections": ["Objective"]}
        result = _run_case(case, prompt, {}, lint_r, scan_r, tok, score)
        assert not result.passed


class TestRegexAssertions:
    def test_regex_match_passes(self):
        lint_r, scan_r, tok, score = _empty_results()
        case = {"name": "t", "regex_match": [r"\bstop\b"]}
        result = _run_case(case, "stop if tests fail", {}, lint_r, scan_r, tok, score)
        assert result.passed

    def test_regex_match_fails(self):
        lint_r, scan_r, tok, score = _empty_results()
        case = {"name": "t", "regex_match": [r"\bdeploy\b"]}
        result = _run_case(case, "no deployment here", {}, lint_r, scan_r, tok, score)
        assert not result.passed

    def test_regex_not_match_passes(self):
        lint_r, scan_r, tok, score = _empty_results()
        case = {"name": "t", "regex_not_match": [r"\bdeploy\b"]}
        result = _run_case(case, "safe prompt", {}, lint_r, scan_r, tok, score)
        assert result.passed

    def test_regex_not_match_fails(self):
        lint_r, scan_r, tok, score = _empty_results()
        case = {"name": "t", "regex_not_match": [r"\bdeploy\b"]}
        result = _run_case(case, "please deploy to production", {}, lint_r, scan_r, tok, score)
        assert not result.passed

    def test_invalid_regex_produces_failed_assertion(self):
        lint_r, scan_r, tok, score = _empty_results()
        case = {"name": "t", "regex_match": [r"[invalid"]}
        result = _run_case(case, "any text", {}, lint_r, scan_r, tok, score)
        assert not result.passed
        assert "invalid regex" in result.assertions[-1].actual


# ── PromptTestSuiteResult properties ─────────────────────────────────────────


class TestSuiteResultProperties:
    def test_passed_all_pass(self):
        suite = PromptTestSuiteResult(
            prompt_path="p",
            target="claude",
            description="",
            cases=[
                PromptTestCaseResult(name="a", passed=True),
                PromptTestCaseResult(name="b", passed=True),
            ],
        )
        assert suite.passed
        assert suite.pass_count == 2
        assert suite.fail_count == 0

    def test_not_passed_when_one_fails(self):
        suite = PromptTestSuiteResult(
            prompt_path="p",
            target="claude",
            description="",
            cases=[
                PromptTestCaseResult(name="a", passed=True),
                PromptTestCaseResult(name="b", passed=False),
            ],
        )
        assert not suite.passed
        assert suite.fail_count == 1

    def test_failure_count_on_case(self):
        case = PromptTestCaseResult(
            name="x",
            passed=False,
            assertions=[
                PromptTestAssertion(kind="k", detail="d", passed=True),
                PromptTestAssertion(kind="k", detail="d", passed=False),
            ],
        )
        assert case.failure_count == 1


# ── run_test_suite integration ────────────────────────────────────────────────


class TestRunTestSuite:
    def test_run_full_suite(self):
        prompt = (
            "## Objective\nRefactor auth module using Claude Code.\n"
            "## Stop Conditions\nStop if tests fail.\n"
            "## Scope\nOnly src/auth/\n"
            "## Forbidden Actions\nDo not modify migrations.\n"
            "## Output Format\nDiff + test results.\n"
            "## Acceptance Criteria\nDone when all tests pass."
        )
        suite_yaml = """
prompt: prompt.md
target: claude-code
description: "Integration test"

tests:
  - name: has objective
    required_sections:
      - Objective
  - name: mentions auth
    must_include:
      - auth
  - name: no deploy
    must_not_include:
      - deploy to production
"""
        suite_path, _ = _make_suite_files(prompt, suite_yaml)
        result = run_test_suite(str(suite_path))
        assert result.passed
        assert result.total == 3

    def test_missing_prompt_file_raises(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        suite_path = tmp / "suite.prompt-test.yaml"
        suite_path.write_text("prompt: nonexistent.md\ntests: []\n")
        with pytest.raises(FileNotFoundError):
            run_test_suite(str(suite_path))
