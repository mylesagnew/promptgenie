"""Tests for promptgenie.core.variables — interactive variable resolver."""

from __future__ import annotations

import pytest

from promptgenie.core.errors import EXIT_USAGE, PromptGenieError
from promptgenie.core.variables import (
    VariableSpec,
    VarResolutionError,
    find_variables,
    load_schema_file,
    load_vars_file,
    parse_cli_vars,
    resolve_variables,
)

# ---------------------------------------------------------------------------
# find_variables
# ---------------------------------------------------------------------------


class TestFindVariables:
    def test_no_placeholders(self):
        assert find_variables("plain text") == []

    def test_single_placeholder(self):
        assert find_variables("Hello {{name}}!") == ["name"]

    def test_multiple_placeholders_ordered(self):
        result = find_variables("{{a}} and {{b}} and {{a}} again")
        assert result == ["a", "b"]  # deduplicated, order preserved

    def test_placeholder_with_type(self):
        assert find_variables("Value: {{count:int}}") == ["count"]

    def test_placeholder_with_type_and_default(self):
        assert find_variables("Env: {{env:string:prod}}") == ["env"]

    def test_invalid_placeholder_not_matched(self):
        # Placeholders must start with letter or underscore
        assert find_variables("{{ 123bad }}") == []

    def test_multiple_unique(self):
        text = "{{x}} {{y}} {{z}}"
        assert find_variables(text) == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# parse_cli_vars
# ---------------------------------------------------------------------------


class TestParseCliVars:
    def test_basic_kv(self):
        assert parse_cli_vars(["key=value"]) == {"key": "value"}

    def test_multiple(self):
        assert parse_cli_vars(["a=1", "b=2"]) == {"a": "1", "b": "2"}

    def test_value_with_equals(self):
        # Only first = is the separator
        result = parse_cli_vars(["url=http://example.com/path?x=1"])
        assert result == {"url": "http://example.com/path?x=1"}

    def test_invalid_no_equals_raises(self):
        with pytest.raises(Exception) as exc_info:
            parse_cli_vars(["noequals"])
        assert (
            "key=value" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()
        )

    def test_empty_list(self):
        assert parse_cli_vars([]) == {}


# ---------------------------------------------------------------------------
# load_vars_file
# ---------------------------------------------------------------------------


class TestLoadVarsFile:
    def test_load_simple_yaml(self, tmp_path):
        f = tmp_path / "vars.yaml"
        f.write_text("env: prod\nregion: us-east-1\n")
        assert load_vars_file(f) == {"env": "prod", "region": "us-east-1"}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, PromptGenieError)):
            load_vars_file(tmp_path / "nonexistent.yaml")

    def test_non_mapping_raises(self, tmp_path):
        f = tmp_path / "vars.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises((PromptGenieError, TypeError, ValueError)):
            load_vars_file(f)

    def test_invalid_yaml_raises(self, tmp_path):
        f = tmp_path / "vars.yaml"
        f.write_text("key: [\nunclosed")
        with pytest.raises((PromptGenieError, Exception)):
            load_vars_file(f)


# ---------------------------------------------------------------------------
# load_schema_file
# ---------------------------------------------------------------------------


class TestLoadSchemaFile:
    def test_load_schema(self, tmp_path):
        schema_yaml = """
variables:
  api_key:
    type: secret
    required: true
  env:
    type: string
    default: staging
    required: false
    allowed_values: [prod, staging, dev]
"""
        f = tmp_path / "schema.yaml"
        f.write_text(schema_yaml)
        result = load_schema_file(f)
        assert "api_key" in result
        assert result["api_key"].secret is True
        assert result["api_key"].required is True
        assert "env" in result
        assert result["env"].default == "staging"
        assert result["env"].required is False
        assert result["env"].allowed_values == ["prod", "staging", "dev"]

    def test_missing_schema_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, PromptGenieError)):
            load_schema_file(tmp_path / "missing.yaml")


# ---------------------------------------------------------------------------
# resolve_variables — no_input mode
# ---------------------------------------------------------------------------


class TestResolveVariablesNoInput:
    def test_cli_vars_override(self):
        text = "Deploy to {{env}}"
        rendered, resolved = resolve_variables(
            text,
            cli_vars={"env": "prod"},
            no_input=True,
        )
        assert rendered == "Deploy to prod"
        assert resolved["env"] == "prod"

    def test_vars_file_used(self):
        text = "Hello {{name}}!"
        rendered, resolved = resolve_variables(
            text,
            vars_file_values={"name": "world"},
            no_input=True,
        )
        assert rendered == "Hello world!"

    def test_cli_overrides_vars_file(self):
        text = "{{env}}"
        rendered, _ = resolve_variables(
            text,
            cli_vars={"env": "prod"},
            vars_file_values={"env": "staging"},
            no_input=True,
        )
        assert rendered == "prod"

    def test_inline_default_used_when_no_value(self):
        text = "Region: {{region:string:us-east-1}}"
        rendered, resolved = resolve_variables(text, no_input=True)
        assert rendered == "Region: us-east-1"
        assert resolved["region"] == "us-east-1"

    def test_required_unresolved_raises(self):
        text = "Hello {{name}}"
        with pytest.raises(VarResolutionError) as exc_info:
            resolve_variables(text, no_input=True)
        assert exc_info.value.var_name == "name"
        assert exc_info.value.code == EXIT_USAGE

    def test_env_var_resolution(self, monkeypatch):
        monkeypatch.setenv("PG_TARGET_ENV", "production")
        text = "Deploying to {{target_env}}"
        rendered, _ = resolve_variables(text, no_input=True)
        assert rendered == "Deploying to production"

    def test_custom_env_prefix(self, monkeypatch):
        monkeypatch.setenv("MY_FOO", "bar")
        text = "Value: {{foo}}"
        rendered, _ = resolve_variables(text, env_prefix="MY_", no_input=True)
        assert rendered == "Value: bar"

    def test_no_placeholders_returns_text_unchanged(self):
        text = "No placeholders here."
        rendered, resolved = resolve_variables(text, no_input=True)
        assert rendered == text
        assert resolved == {}

    def test_multiple_occurrences_same_variable(self):
        text = "{{x}} and {{x}} again"
        rendered, _ = resolve_variables(text, cli_vars={"x": "hello"}, no_input=True)
        assert rendered == "hello and hello again"

    def test_allowed_values_valid(self):
        schema = {"env": VariableSpec(name="env", allowed_values=["prod", "staging"])}
        text = "{{env}}"
        rendered, _ = resolve_variables(
            text, cli_vars={"env": "prod"}, schema=schema, no_input=True
        )
        assert rendered == "prod"

    def test_allowed_values_invalid_raises(self):
        schema = {"env": VariableSpec(name="env", allowed_values=["prod", "staging"])}
        text = "{{env}}"
        with pytest.raises((PromptGenieError, ValueError)):
            resolve_variables(text, cli_vars={"env": "dev"}, schema=schema, no_input=True)

    def test_secret_masked_in_display(self):
        schema = {"token": VariableSpec(name="token", secret=True)}
        text = "Token: {{token}}"
        rendered, display = resolve_variables(
            text, cli_vars={"token": "supersecret"}, schema=schema, no_input=True
        )
        assert rendered == "Token: supersecret"
        assert display["token"] == "***"

    def test_type_coercion_int_valid(self):
        text = "Count: {{n:int}}"
        rendered, _ = resolve_variables(text, cli_vars={"n": "42"}, no_input=True)
        assert rendered == "Count: 42"

    def test_type_coercion_int_invalid_raises(self):
        text = "Count: {{n:int}}"
        with pytest.raises((PromptGenieError, ValueError)):
            resolve_variables(text, cli_vars={"n": "not-an-int"}, no_input=True)


# ---------------------------------------------------------------------------
# VarResolutionError
# ---------------------------------------------------------------------------


class TestVarResolutionError:
    def test_has_var_name(self):
        err = VarResolutionError("my_var")
        assert err.var_name == "my_var"

    def test_has_correct_exit_code(self):
        err = VarResolutionError("x")
        assert err.code == EXIT_USAGE

    def test_hint_mentions_var_flag(self):
        err = VarResolutionError("api_key")
        assert "--var" in err.hint
