"""Tests for promptgenie.core.spec — PromptSpec loader and validator."""

from __future__ import annotations

import json

import pytest
import yaml

from promptgenie.core.errors import PromptGenieError
from promptgenie.core.spec import (
    SPEC_SCHEMA_PATH,
    PromptSpec,
    _validate_raw,
    load_spec,
    render_spec,
    spec_init_template,
    validate_spec,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


MINIMAL_SPEC = {
    "version": 1,
    "name": "test-spec",
    "target": "claude-code",
}

FULL_SPEC = {
    "version": 1,
    "name": "full-spec",
    "target": "claude-code",
    "template": "agentic-task",
    "mode": "chat",
    "vars": {"env": "prod", "component": "auth"},
    "context": [
        {"type": "git_diff"},
        {"type": "file", "path": "README.md", "label": "readme"},
    ],
    "policy": ["no-secrets"],
    "provider": "anthropic",
    "model": "claude-opus-4-5",
    "system_prompt": "You are a code reviewer.",
    "prompt": "Review {{component}} in {{env}}.",
    "output_contract": {
        "format": "markdown",
        "max_tokens": 2048,
    },
    "run": {
        "stream": True,
        "timeout": 60,
        "dry_run": False,
        "require_clean": True,
    },
}


# ---------------------------------------------------------------------------
# _validate_raw
# ---------------------------------------------------------------------------


class TestValidateRaw:
    def test_valid_minimal(self):
        assert _validate_raw(MINIMAL_SPEC) == []

    def test_valid_full(self):
        assert _validate_raw(FULL_SPEC) == []

    def test_missing_version(self):
        raw = {**MINIMAL_SPEC, "version": 2}
        errors = _validate_raw(raw)
        assert any("version" in e for e in errors)

    def test_missing_name(self):
        raw = {**MINIMAL_SPEC, "name": ""}
        errors = _validate_raw(raw)
        assert any("name" in e for e in errors)

    def test_missing_target(self):
        raw = {**MINIMAL_SPEC, "target": ""}
        errors = _validate_raw(raw)
        assert any("target" in e for e in errors)

    def test_invalid_mode(self):
        raw = {**MINIMAL_SPEC, "mode": "turbo"}
        errors = _validate_raw(raw)
        assert any("mode" in e for e in errors)

    def test_invalid_context_type(self):
        raw = {**MINIMAL_SPEC, "context": [{"type": "ftp"}]}
        errors = _validate_raw(raw)
        assert any("context[0].type" in e for e in errors)

    def test_invalid_output_format(self):
        raw = {**MINIMAL_SPEC, "output_contract": {"format": "csv"}}
        errors = _validate_raw(raw)
        assert any("output_contract.format" in e for e in errors)

    def test_valid_all_context_types(self):
        types = ["file", "glob", "stdin", "env", "cmd", "git_diff", "git_staged", "url"]
        for t in types:
            raw = {**MINIMAL_SPEC, "context": [{"type": t}]}
            assert _validate_raw(raw) == [], f"Expected no errors for type={t}"

    def test_context_non_mapping_is_error(self):
        raw = {**MINIMAL_SPEC, "context": ["not-a-dict"]}
        errors = _validate_raw(raw)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# load_spec
# ---------------------------------------------------------------------------


class TestLoadSpec:
    def test_load_minimal_yaml(self, tmp_path):
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.dump(MINIMAL_SPEC), encoding="utf-8")
        spec = load_spec(f)
        assert spec.name == "test-spec"
        assert spec.target == "claude-code"
        assert spec.version == 1

    def test_load_full_yaml(self, tmp_path):
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.dump(FULL_SPEC), encoding="utf-8")
        spec = load_spec(f)
        assert spec.name == "full-spec"
        assert spec.model == "claude-opus-4-5"
        assert len(spec.context) == 2
        assert spec.context[0].type == "git_diff"
        assert spec.context[1].label == "readme"
        assert spec.output_contract.format == "markdown"
        assert spec.run.require_clean is True

    def test_load_json(self, tmp_path):
        f = tmp_path / "spec.json"
        f.write_text(json.dumps(MINIMAL_SPEC), encoding="utf-8")
        spec = load_spec(f)
        assert spec.name == "test-spec"

    def test_load_missing_file_raises(self):
        with pytest.raises(PromptGenieError) as exc_info:
            load_spec("/nonexistent/path/spec.yaml")
        assert "not found" in str(exc_info.value).lower()

    def test_load_invalid_yaml_raises(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("version: 1\nname: [unclosed", encoding="utf-8")
        with pytest.raises(PromptGenieError):
            load_spec(f)

    def test_load_not_a_mapping_raises(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(PromptGenieError):
            load_spec(f)

    def test_load_invalid_spec_raises(self, tmp_path):
        raw = {"version": 1, "name": "x", "target": "y", "mode": "invalid-mode"}
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.dump(raw), encoding="utf-8")
        with pytest.raises(PromptGenieError):
            load_spec(f)

    def test_source_path_is_set(self, tmp_path):
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.dump(MINIMAL_SPEC), encoding="utf-8")
        spec = load_spec(f)
        assert spec._source_path == f

    def test_defaults_applied(self, tmp_path):
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.dump(MINIMAL_SPEC), encoding="utf-8")
        spec = load_spec(f)
        assert spec.mode == "chat"
        assert spec.run.timeout == 120
        assert spec.run.stream is True
        assert spec.output_contract.format == "text"


# ---------------------------------------------------------------------------
# validate_spec
# ---------------------------------------------------------------------------


class TestValidateSpec:
    def test_valid_spec_returns_empty(self, tmp_path):
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.dump(FULL_SPEC), encoding="utf-8")
        spec = load_spec(f)
        assert validate_spec(spec) == []

    def test_invalid_mode_returns_error(self, tmp_path):
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.dump(MINIMAL_SPEC), encoding="utf-8")
        spec = load_spec(f)
        spec.mode = "turbo"
        errors = validate_spec(spec)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# render_spec
# ---------------------------------------------------------------------------


class TestRenderSpec:
    def _make_spec(self, prompt: str = "") -> PromptSpec:
        return PromptSpec(
            version=1,
            name="test",
            target="claude-code",
            prompt=prompt,
        )

    def test_simple_substitution(self):
        spec = self._make_spec("Deploy {{service}} to {{env}}")
        result = render_spec(spec, {"service": "api", "env": "prod"})
        assert result == "Deploy api to prod"

    def test_missing_var_unchanged(self):
        spec = self._make_spec("Hello {{name}}")
        result = render_spec(spec, {})
        assert "{{name}}" in result

    def test_empty_prompt(self):
        spec = self._make_spec("")
        result = render_spec(spec, {"x": "y"})
        assert result == ""

    def test_template_reference_when_no_prompt(self):
        spec = PromptSpec(
            version=1,
            name="test",
            target="claude-code",
            template="agentic-task",
        )
        result = render_spec(spec, {})
        assert "agentic-task" in result


# ---------------------------------------------------------------------------
# spec_init_template
# ---------------------------------------------------------------------------


class TestSpecInitTemplate:
    def test_returns_string(self):
        t = spec_init_template("my-spec")
        assert isinstance(t, str)

    def test_contains_name(self):
        t = spec_init_template("code-review")
        assert "code-review" in t

    def test_contains_target(self):
        t = spec_init_template("x", target="ollama")
        assert "ollama" in t

    def test_is_valid_yaml(self):
        t = spec_init_template("test-spec")
        parsed = yaml.safe_load(t)
        assert isinstance(parsed, dict)
        assert parsed["version"] == 1


# ---------------------------------------------------------------------------
# Schema file
# ---------------------------------------------------------------------------


class TestSchemaFile:
    def test_schema_file_exists(self):
        assert SPEC_SCHEMA_PATH.exists()

    def test_schema_file_is_valid_json(self):
        data = json.loads(SPEC_SCHEMA_PATH.read_text())
        assert data["title"] == "PromptSpec"
        assert "$defs" in data

    def test_schema_has_required_fields(self):
        data = json.loads(SPEC_SCHEMA_PATH.read_text())
        assert "version" in data["required"]
        assert "name" in data["required"]
        assert "target" in data["required"]
