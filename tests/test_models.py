"""Tests for promptgenie/models.py — typed result and config models (Wave 5)."""

from pathlib import Path

import pytest

from promptgenie.models import (
    ContextPackMeta,
    GenerateResult,
    Profile,
    Template,
    ValidationResult,
)


class TestProfile:
    def test_from_dict_basic(self):
        data = {
            "name": "Claude Code",
            "category": "agentic",
            "required_sections": ["Objective", "Scope"],
            "forbidden_patterns": ["rm -rf"],
        }
        profile = Profile.from_dict(data, profile_id="claude-code")
        assert profile.id == "claude-code"
        assert profile.name == "Claude Code"
        assert profile.category == "agentic"
        assert "Objective" in profile.required_sections

    def test_from_dict_defaults(self):
        profile = Profile.from_dict({}, profile_id="x")
        assert profile.name == "x"  # falls back to id
        assert profile.required_sections == []
        assert profile.default_output_format == "Structured markdown."

    def test_validate_passes_with_name(self):
        profile = Profile.from_dict({"name": "Test"}, "test")
        assert profile.validate() == []

    def test_validate_fails_without_name(self):
        profile = Profile(id="x", name="")
        errors = profile.validate()
        assert errors


class TestTemplate:
    def test_from_dict_basic(self):
        data = {"id": "agentic-task", "name": "Agentic Task", "sections": ["Objective", "Scope"]}
        tmpl = Template.from_dict(data)
        assert tmpl.id == "agentic-task"
        assert tmpl.name == "Agentic Task"
        assert "Objective" in tmpl.sections

    def test_validate_passes(self):
        tmpl = Template.from_dict({"id": "t", "name": "T"})
        assert tmpl.validate() == []

    def test_validate_fails_no_id(self):
        tmpl = Template(id="", name="Test")
        assert tmpl.validate()

    def test_validate_fails_no_name(self):
        tmpl = Template(id="t", name="")
        assert tmpl.validate()


class TestContextPackMeta:
    def test_from_dict(self):
        data = {"name": "React App", "description": "SaaS app", "stack": ["React", "Supabase"]}
        meta = ContextPackMeta.from_dict(data, pack_id="react-supabase-app")
        assert meta.id == "react-supabase-app"
        assert meta.name == "React App"
        assert "React" in meta.stack


class TestGenerateResult:
    def _make(self, score_total=80, lint_issues=None, findings=None):
        from promptgenie.core.linter import LintIssue
        from promptgenie.core.scanner import SecurityFinding
        return GenerateResult(
            prompt="## Objective\nDo the thing.",
            target="claude-code",
            template="agentic-task",
            token_estimate=100,
            score={"total": score_total, "breakdown": {}},
            lint_issues=lint_issues or [],
            scan_findings=findings or [],
        )

    def test_score_total(self):
        r = self._make(score_total=75)
        assert r.score_total == 75

    def test_has_high_lint_false(self):
        r = self._make()
        assert not r.has_high_lint

    def test_has_high_lint_true(self):
        from promptgenie.core.linter import LintIssue
        r = self._make(lint_issues=[LintIssue(severity="HIGH", code="X", message="m")])
        assert r.has_high_lint

    def test_has_critical_security_false(self):
        r = self._make()
        assert not r.has_critical_security

    def test_has_critical_security_true(self):
        from promptgenie.core.scanner import SecurityFinding
        r = self._make(findings=[SecurityFinding(risk="CRITICAL", code="X", message="m")])
        assert r.has_critical_security


class TestValidationResult:
    def test_str_valid(self):
        r = ValidationResult(path=Path("foo.yaml"), kind="profile", valid=True)
        assert "✓" in str(r)
        assert "profile" in str(r)

    def test_str_invalid_shows_errors(self):
        r = ValidationResult(
            path=Path("bad.yaml"), kind="workflow", valid=False, errors=["Missing 'name'."]
        )
        s = str(r)
        assert "✗" in s
        assert "Missing 'name'." in s

    def test_str_shows_warnings(self):
        r = ValidationResult(
            path=Path("ok.yaml"), kind="prompt-test", valid=True, warnings=["No tests found."]
        )
        assert "No tests found." in str(r)
