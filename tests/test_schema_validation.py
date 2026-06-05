"""Tests for enhanced schema validation in models.py and validate-profiles command."""

import tempfile
from pathlib import Path

import yaml
from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.models import ContextPackMeta, Profile, Template

# ── Profile.validate() ────────────────────────────────────────────────────────


class TestProfileValidation:
    def _make(self, **kwargs) -> Profile:
        base = {
            "name": "Test Profile",
            "category": "agentic-coding",
            "required_sections": ["Objective", "Scope"],
            "stop_conditions": ["Ask before modifying outside scope"],
            "scope_guidance": "Work within listed files only.",
        }
        base.update(kwargs)
        return Profile.from_dict(base, profile_id="test")

    def test_valid_profile_has_no_errors(self):
        errors, warnings = self._make().validate()
        assert errors == []

    def test_missing_name_is_error(self):
        # name must be explicitly empty string to trigger error (from_dict falls back to profile_id)
        p = Profile.from_dict({"name": "", "category": "agentic-coding"}, profile_id="test")
        errors, _ = p.validate()
        assert any("name" in e for e in errors)

    def test_blank_name_is_error(self):
        errors, _ = self._make(name="   ").validate()
        assert any("name" in e for e in errors)

    def test_missing_category_is_error(self):
        p = Profile.from_dict({"name": "Test"}, profile_id="test")
        errors, _ = p.validate()
        assert any("category" in e for e in errors)

    def test_unknown_category_is_warning(self):
        _, warnings = self._make(category="made-up-category").validate()
        assert any("category" in w for w in warnings)

    def test_known_category_no_warning(self):
        _, warnings = self._make(category="agentic-coding").validate()
        assert not any("category" in w for w in warnings)

    def test_empty_required_sections_is_warning(self):
        _, warnings = self._make(required_sections=[]).validate()
        assert any("required_sections" in w for w in warnings)

    def test_empty_stop_conditions_is_warning(self):
        _, warnings = self._make(stop_conditions=[]).validate()
        assert any("stop_conditions" in w for w in warnings)

    def test_non_list_required_sections_is_error(self):
        errors, _ = self._make(required_sections="Objective").validate()
        assert any("required_sections" in e for e in errors)

    def test_list_with_non_string_item_is_error(self):
        errors, _ = self._make(required_sections=["Objective", 42]).validate()
        assert any("required_sections" in e for e in errors)

    def test_list_with_blank_item_is_error(self):
        errors, _ = self._make(stop_conditions=["valid", ""]).validate()
        assert any("stop_conditions" in e for e in errors)

    def test_non_string_scope_guidance_is_error(self):
        errors, _ = self._make(scope_guidance=["list", "not", "string"]).validate()
        assert any("scope_guidance" in e for e in errors)

    def test_unknown_key_produces_warning(self):
        data = {
            "name": "X",
            "category": "agentic-coding",
            "required_sections": ["Objective"],
            "stop_conditions": ["Ask"],
            "scope_guidance": "Yes",
            "typo_key": "oops",
        }
        p = Profile.from_dict(data, profile_id="test")
        _, warnings = p.validate()
        assert any("typo_key" in w for w in warnings)

    def test_missing_scope_guidance_is_warning(self):
        _, warnings = self._make(scope_guidance="").validate()
        assert any("scope_guidance" in w for w in warnings)


# ── Template.validate() ───────────────────────────────────────────────────────


class TestTemplateValidation:
    def _make(self, **kwargs) -> Template:
        base = {
            "id": "my-template",
            "name": "My Template",
            "description": "Does stuff.",
            "sections": ["Objective", "Scope"],
        }
        base.update(kwargs)
        return Template.from_dict(base)

    def test_valid_template_has_no_errors(self):
        errors, warnings = self._make().validate()
        assert errors == []
        assert warnings == []

    def test_missing_id_is_error(self):
        errors, _ = self._make(id="").validate()
        assert any("id" in e for e in errors)

    def test_invalid_id_slug_is_error(self):
        errors, _ = self._make(id="My Template!").validate()
        assert any("id" in e for e in errors)

    def test_valid_slug_ids(self):
        for slug in ("my-template", "threat-model", "a1b2", "template"):
            errors, _ = self._make(id=slug).validate()
            assert errors == [], f"Expected valid slug {slug!r} to pass"

    def test_invalid_slug_ids(self):
        for slug in ("My Template", "UPPER", "with spaces", "has_underscore", "-starts-dash"):
            errors, _ = self._make(id=slug).validate()
            assert any("id" in e for e in errors), f"Expected invalid slug {slug!r} to fail"

    def test_missing_name_is_error(self):
        errors, _ = self._make(name="").validate()
        assert any("name" in e for e in errors)

    def test_empty_sections_is_error(self):
        errors, _ = self._make(sections=[]).validate()
        assert any("sections" in e for e in errors)

    def test_non_list_sections_is_error(self):
        errors, _ = self._make(sections="Objective").validate()
        assert any("sections" in e for e in errors)

    def test_section_with_non_string_item_is_error(self):
        errors, _ = self._make(sections=["Objective", None]).validate()
        assert any("sections" in e for e in errors)

    def test_missing_description_is_warning(self):
        _, warnings = self._make(description="").validate()
        assert any("description" in w for w in warnings)

    def test_unknown_key_produces_warning(self):
        data = {
            "id": "my-template",
            "name": "My Template",
            "sections": ["Objective"],
            "unknown_field": "oops",
        }
        _, warnings = Template.from_dict(data).validate()
        assert any("unknown_field" in w for w in warnings)


# ── ContextPackMeta.validate() ────────────────────────────────────────────────


class TestContextPackValidation:
    def _make(self, **kwargs) -> ContextPackMeta:
        base = {
            "name": "My App",
            "description": "A test app.",
            "stack": ["Python 3.12", "FastAPI"],
        }
        base.update(kwargs)
        return ContextPackMeta.from_dict(base, pack_id="my-app")

    def test_valid_pack_has_no_errors(self):
        errors, warnings = self._make().validate()
        assert errors == []

    def test_missing_name_is_error(self):
        errors, _ = self._make(name="").validate()
        assert any("name" in e for e in errors)

    def test_missing_description_is_warning(self):
        _, warnings = self._make(description="").validate()
        assert any("description" in w for w in warnings)

    def test_empty_stack_is_warning(self):
        _, warnings = self._make(stack=[]).validate()
        assert any("stack" in w for w in warnings)

    def test_non_list_stack_is_error(self):
        errors, _ = self._make(stack="Python").validate()
        assert any("stack" in e for e in errors)

    def test_unknown_key_produces_warning(self):
        data = {"name": "App", "description": "x", "stack": ["Python"], "surprise": True}
        _, warnings = ContextPackMeta.from_dict(data, pack_id="app").validate()
        assert any("surprise" in w for w in warnings)


# ── validate-profiles command ─────────────────────────────────────────────────


class TestValidateProfilesCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_validates_builtin_profiles(self):
        result = self.runner.invoke(cli, ["validate-profiles"])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_validates_custom_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = {
                "name": "Custom Profile",
                "category": "agentic-coding",
                "required_sections": ["Objective"],
                "stop_conditions": ["Ask before changing scope"],
                "scope_guidance": "Stay within listed files.",
            }
            (Path(tmp) / "custom.yaml").write_text(yaml.dump(profile))
            result = self.runner.invoke(cli, ["validate-profiles", "--dir", tmp])
            assert result.exit_code == 0
            assert "✓" in result.output

    def test_invalid_profile_in_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = {"name": "", "category": "agentic-coding"}  # blank name → error
            (Path(tmp) / "bad.yaml").write_text(yaml.dump(bad))
            result = self.runner.invoke(cli, ["validate-profiles", "--dir", tmp])
            assert result.exit_code == 1
            assert "ERROR" in result.output

    def test_empty_dir_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.runner.invoke(cli, ["validate-profiles", "--dir", tmp])
            assert result.exit_code == 0
            assert "No YAML files" in result.output

    def test_no_warnings_flag_suppresses_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Valid but missing optional fields to trigger warnings
            profile = {"name": "Minimal", "category": "agentic-coding"}
            (Path(tmp) / "minimal.yaml").write_text(yaml.dump(profile))
            result_with = self.runner.invoke(cli, ["validate-profiles", "--dir", tmp, "--warnings"])
            result_without = self.runner.invoke(
                cli, ["validate-profiles", "--dir", tmp, "--no-warnings"]
            )
            # With warnings: should show WARN lines
            assert "WARN" in result_with.output
            # Without warnings: no WARN lines
            assert "WARN" not in result_without.output

    def test_warnings_shown_but_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Valid profile but missing optional recommended fields
            profile = {"name": "Minimal", "category": "agentic-coding"}
            (Path(tmp) / "minimal.yaml").write_text(yaml.dump(profile))
            result = self.runner.invoke(cli, ["validate-profiles", "--dir", tmp])
            # Exits 0 (warnings don't fail) but shows warnings
            assert result.exit_code == 0
            assert "WARN" in result.output


# ── validate --all now shows warnings ────────────────────────────────────────


class TestValidateAllWithWarnings:
    def setup_method(self):
        self.runner = CliRunner()

    def test_validate_all_passes_and_shows_warning_count(self):
        result = self.runner.invoke(cli, ["validate", "--all"])
        assert result.exit_code == 0
        # Should still say all valid (warnings don't fail)
        assert "valid" in result.output.lower()

    def test_profile_with_unknown_key_shows_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {
                "name": "Test",
                "category": "agentic-coding",
                "required_sections": ["Objective"],
                "stop_conditions": ["Ask"],
                "scope_guidance": "Ok.",
                "oops_key": "surprise",
            }
            path = Path(tmp) / "test.yaml"
            path.write_text(yaml.dump(data))
            result = self.runner.invoke(cli, ["validate", str(path)])
            assert result.exit_code == 0  # warning, not error
            assert "WARN" in result.output
            assert "oops_key" in result.output
