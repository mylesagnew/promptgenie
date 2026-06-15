"""Tests for workspace schema: WorkspaceConfig, DefaultsConfig, validate_workspace_config,
config validate command, and config init command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.config import (
    DefaultsConfig,
    PromptGenieConfig,
    WorkspaceConfig,
    validate_workspace_config,
)


# ---------------------------------------------------------------------------
# WorkspaceConfig / DefaultsConfig dataclasses
# ---------------------------------------------------------------------------


class TestWorkspaceConfig:
    def test_defaults_are_empty_strings(self):
        ws = WorkspaceConfig()
        assert ws.name == ""
        assert ws.version == ""
        assert ws.team == ""
        assert ws.description == ""
        assert ws.policy == ""

    def test_fields_set_correctly(self):
        ws = WorkspaceConfig(name="myproject", version="1.0", team="acme",
                             description="A test project", policy=".policy.yaml")
        assert ws.name == "myproject"
        assert ws.version == "1.0"
        assert ws.team == "acme"
        assert ws.description == "A test project"
        assert ws.policy == ".policy.yaml"


class TestDefaultsConfig:
    def test_defaults_are_empty_strings(self):
        df = DefaultsConfig()
        assert df.provider == ""
        assert df.model == ""
        assert df.target == ""

    def test_fields_set_correctly(self):
        df = DefaultsConfig(provider="anthropic", model="claude-opus-4-5", target="claude-code")
        assert df.provider == "anthropic"
        assert df.model == "claude-opus-4-5"
        assert df.target == "claude-code"


class TestPromptGenieConfigExpanded:
    def test_has_workspace_and_defaults_fields(self):
        cfg = PromptGenieConfig()
        assert isinstance(cfg.workspace, WorkspaceConfig)
        assert isinstance(cfg.defaults, DefaultsConfig)

    def test_load_config_parses_workspace(self, tmp_path):
        from promptgenie.core.config import load_config

        cfg_file = tmp_path / ".promptgenie.yaml"
        cfg_file.write_text(
            "workspace:\n  name: testproj\n  team: engteam\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        assert cfg.workspace.name == "testproj"
        assert cfg.workspace.team == "engteam"

    def test_load_config_parses_defaults(self, tmp_path):
        from promptgenie.core.config import load_config

        cfg_file = tmp_path / ".promptgenie.yaml"
        cfg_file.write_text(
            "defaults:\n  provider: ollama\n  model: llama3\n  target: chatgpt\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        assert cfg.defaults.provider == "ollama"
        assert cfg.defaults.model == "llama3"
        assert cfg.defaults.target == "chatgpt"

    def test_load_config_empty_file_gives_empty_workspace(self, tmp_path):
        from promptgenie.core.config import load_config

        cfg_file = tmp_path / ".promptgenie.yaml"
        cfg_file.write_text("{}", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.workspace.name == ""
        assert cfg.defaults.provider == ""


# ---------------------------------------------------------------------------
# validate_workspace_config — happy path
# ---------------------------------------------------------------------------


class TestValidateWorkspaceConfigValid:
    def test_empty_dict_is_valid(self):
        errors, warnings = validate_workspace_config({})
        assert errors == []

    def test_schema_key_is_allowed(self):
        errors, _ = validate_workspace_config(
            {"$schema": "https://promptgenie.dev/schemas/workspace.schema.json"}
        )
        assert errors == []

    def test_full_valid_config(self):
        raw = {
            "workspace": {"name": "myproj", "team": "eng", "version": "1.0"},
            "defaults": {"provider": "anthropic", "model": "claude-opus-4-5"},
            "security": {"airgap": False, "block_secrets": True},
            "routing": {
                "default": "anthropic",
                "rules": [{"if": "contains_secrets", "provider": "ollama"}],
            },
            "scanner": {
                "disabled_rules": ["PERM_001"],
                "severity_overrides": {"PERM_002": "LOW"},
                "allowlist": ["known-safe-token"],
            },
            "linter": {
                "disabled_rules": ["TASK_001"],
                "custom_vague_verbs": ["handle"],
            },
        }
        errors, _ = validate_workspace_config(raw)
        assert errors == []

    def test_allowlist_full_object_form_is_valid(self):
        raw = {
            "scanner": {
                "allowlist": [
                    {"phrase": "example-ci-token", "rules": ["PERM_001"],
                     "expires": "2030-01-01", "reason": "CI placeholder"}
                ]
            }
        }
        errors, _ = validate_workspace_config(raw)
        assert errors == []

    def test_custom_scan_rule_valid(self):
        raw = {
            "scanner": {
                "custom_rules": [
                    {"id": "CUSTOM_001", "pattern": r"\bsecret\b",
                     "risk": "HIGH", "confidence": "MEDIUM", "message": "Found secret"}
                ]
            }
        }
        errors, _ = validate_workspace_config(raw)
        assert errors == []

    def test_custom_lint_rule_valid(self):
        raw = {
            "linter": {
                "custom_rules": [
                    {"id": "CLINT_001", "pattern": r"\bhandle\b",
                     "severity": "LOW", "confidence": "HIGH", "message": "Vague verb"}
                ]
            }
        }
        errors, _ = validate_workspace_config(raw)
        assert errors == []


# ---------------------------------------------------------------------------
# validate_workspace_config — unknown keys
# ---------------------------------------------------------------------------


class TestValidateUnknownKeys:
    def test_unknown_top_level_key_is_error(self):
        errors, _ = validate_workspace_config({"typo_key": {}})
        assert any("typo_key" in e for e in errors)

    def test_multiple_unknown_top_level_keys(self):
        errors, _ = validate_workspace_config({"foo": 1, "bar": 2})
        assert len([e for e in errors if "Unknown top-level key" in e]) == 2

    def test_unknown_workspace_key(self):
        errors, _ = validate_workspace_config({"workspace": {"nme": "typo"}})
        assert any("nme" in e for e in errors)

    def test_unknown_defaults_key(self):
        errors, _ = validate_workspace_config({"defaults": {"prvider": "ollama"}})
        assert any("prvider" in e for e in errors)

    def test_unknown_security_key(self):
        errors, _ = validate_workspace_config({"security": {"unknown_flag": True}})
        assert any("unknown_flag" in e for e in errors)

    def test_unknown_scanner_key(self):
        errors, _ = validate_workspace_config({"scanner": {"allowlsit": []}})
        assert any("allowlsit" in e for e in errors)

    def test_unknown_linter_key(self):
        errors, _ = validate_workspace_config({"linter": {"custon_rules": []}})
        assert any("custon_rules" in e for e in errors)

    def test_unknown_routing_key(self):
        errors, _ = validate_workspace_config({"routing": {"defalt": "anthropic"}})
        assert any("defalt" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_workspace_config — type errors
# ---------------------------------------------------------------------------


class TestValidateTypeErrors:
    def test_workspace_not_a_dict(self):
        errors, _ = validate_workspace_config({"workspace": "myproject"})
        assert any("mapping" in e for e in errors)

    def test_security_not_a_dict(self):
        errors, _ = validate_workspace_config({"security": ["airgap"]})
        assert any("mapping" in e for e in errors)

    def test_security_airgap_not_bool(self):
        errors, _ = validate_workspace_config({"security": {"airgap": "yes"}})
        assert any("airgap" in e and "boolean" in e for e in errors)

    def test_workspace_name_not_string(self):
        errors, _ = validate_workspace_config({"workspace": {"name": 42}})
        assert any("workspace.name" in e and "string" in e for e in errors)

    def test_scanner_disabled_rules_not_list(self):
        errors, _ = validate_workspace_config({"scanner": {"disabled_rules": "PERM_001"}})
        assert any("disabled_rules" in e for e in errors)

    def test_scanner_disabled_rules_item_not_string(self):
        errors, _ = validate_workspace_config({"scanner": {"disabled_rules": [1, 2]}})
        assert any("disabled_rules" in e for e in errors)

    def test_routing_rules_not_list(self):
        errors, _ = validate_workspace_config({"routing": {"rules": "all"}})
        assert any("routing.rules" in e for e in errors)

    def test_routing_rule_not_dict(self):
        errors, _ = validate_workspace_config({"routing": {"rules": ["*"]}})
        assert any("routing.rules[0]" in e and "mapping" in e for e in errors)

    def test_routing_rule_missing_if(self):
        errors, _ = validate_workspace_config(
            {"routing": {"rules": [{"provider": "ollama"}]}}
        )
        assert any("'if'" in e for e in errors)

    def test_routing_rule_missing_provider(self):
        errors, _ = validate_workspace_config(
            {"routing": {"rules": [{"if": "*"}]}}
        )
        assert any("'provider'" in e for e in errors)

    def test_top_level_not_dict(self):
        errors, _ = validate_workspace_config("not a dict")  # type: ignore[arg-type]
        assert any("YAML mapping" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_workspace_config — enum / value errors
# ---------------------------------------------------------------------------


class TestValidateEnumErrors:
    def test_severity_override_invalid_value(self):
        errors, _ = validate_workspace_config(
            {"scanner": {"severity_overrides": {"PERM_001": "EXTREME"}}}
        )
        assert any("EXTREME" in e for e in errors)

    def test_severity_override_valid_values(self):
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            errors, _ = validate_workspace_config(
                {"scanner": {"severity_overrides": {"PERM_001": level}}}
            )
            assert errors == [], f"Expected no errors for risk level {level!r}"

    def test_custom_scan_rule_invalid_risk(self):
        raw = {
            "scanner": {
                "custom_rules": [{"id": "C001", "pattern": "x", "risk": "EXTREME"}]
            }
        }
        errors, _ = validate_workspace_config(raw)
        assert any("risk" in e and "EXTREME" in e for e in errors)

    def test_custom_scan_rule_invalid_confidence(self):
        raw = {
            "scanner": {
                "custom_rules": [{"id": "C001", "pattern": "x", "confidence": "MAYBE"}]
            }
        }
        errors, _ = validate_workspace_config(raw)
        assert any("confidence" in e and "MAYBE" in e for e in errors)

    def test_custom_lint_rule_invalid_severity(self):
        raw = {
            "linter": {
                "custom_rules": [{"id": "L001", "pattern": "x", "severity": "WARN"}]
            }
        }
        errors, _ = validate_workspace_config(raw)
        assert any("severity" in e and "WARN" in e for e in errors)

    def test_custom_lint_rule_valid_info_severity(self):
        raw = {
            "linter": {
                "custom_rules": [{"id": "L001", "pattern": "x", "severity": "INFO"}]
            }
        }
        errors, _ = validate_workspace_config(raw)
        assert errors == []


# ---------------------------------------------------------------------------
# validate_workspace_config — allowlist validation
# ---------------------------------------------------------------------------


class TestValidateAllowlist:
    def test_string_entry_valid(self):
        errors, _ = validate_workspace_config(
            {"scanner": {"allowlist": ["known-ci-token"]}}
        )
        assert errors == []

    def test_object_entry_missing_phrase(self):
        errors, _ = validate_workspace_config(
            {"scanner": {"allowlist": [{"expires": "2030-01-01"}]}}
        )
        assert any("phrase" in e for e in errors)

    def test_allowlist_expires_bad_format(self):
        errors, _ = validate_workspace_config(
            {"scanner": {"allowlist": [{"phrase": "x", "expires": "01-01-2030"}]}}
        )
        assert any("YYYY-MM-DD" in e for e in errors)

    def test_allowlist_expires_valid_format(self):
        errors, _ = validate_workspace_config(
            {"scanner": {"allowlist": [{"phrase": "x", "expires": "2030-01-01"}]}}
        )
        assert errors == []

    def test_allowlist_unknown_key_in_object(self):
        errors, _ = validate_workspace_config(
            {"scanner": {"allowlist": [{"phrase": "x", "misspelled_reason": "foo"}]}}
        )
        assert any("misspelled_reason" in e for e in errors)

    def test_allowlist_not_list(self):
        errors, _ = validate_workspace_config(
            {"scanner": {"allowlist": "known-token"}}
        )
        assert any("allowlist" in e for e in errors)

    def test_blank_string_entry_is_warning(self):
        _, warnings = validate_workspace_config(
            {"scanner": {"allowlist": ["  "]}}
        )
        assert any("blank" in w for w in warnings)


# ---------------------------------------------------------------------------
# validate_workspace_config — warnings
# ---------------------------------------------------------------------------


class TestValidateWarnings:
    def test_blank_workspace_name_is_warning(self):
        _, warnings = validate_workspace_config({"workspace": {"name": ""}})
        assert any("workspace.name" in w for w in warnings)

    def test_block_and_redact_both_true_is_warning(self):
        _, warnings = validate_workspace_config(
            {"security": {"block_secrets": True, "redact_secrets": True}}
        )
        assert any("block_secrets" in w and "redact_secrets" in w for w in warnings)

    def test_valid_config_has_no_warnings(self):
        _, warnings = validate_workspace_config(
            {"workspace": {"name": "proj"}, "security": {"airgap": False}}
        )
        assert warnings == []


# ---------------------------------------------------------------------------
# config validate command
# ---------------------------------------------------------------------------


class TestConfigValidateCommand:
    def test_valid_file_exits_0(self, tmp_path):
        cfg_file = tmp_path / ".promptgenie.yaml"
        cfg_file.write_text(
            "workspace:\n  name: testproj\nsecurity:\n  airgap: false\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Write file in isolated dir so auto-discovery finds it
            Path(".promptgenie.yaml").write_text(
                "workspace:\n  name: testproj\nsecurity:\n  airgap: false\n",
                encoding="utf-8",
            )
            result = runner.invoke(cli, ["config", "validate"])
        assert result.exit_code == 0, result.output
        assert "valid" in result.output.lower() or "✓" in result.output

    def test_invalid_file_exits_1(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".promptgenie.yaml").write_text(
                "unknown_section:\n  foo: bar\n", encoding="utf-8"
            )
            result = runner.invoke(cli, ["config", "validate"])
        assert result.exit_code == 1
        assert "error" in result.output.lower() or "unknown" in result.output.lower()

    def test_missing_file_exits_2(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["config", "validate"])
        assert result.exit_code == 2

    def test_explicit_path_valid(self, tmp_path):
        cfg_file = tmp_path / "myconfig.yaml"
        cfg_file.write_text("security:\n  airgap: false\n", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "validate", "--config", str(cfg_file)])
        assert result.exit_code == 0

    def test_explicit_path_not_found_exits_2(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["config", "validate", "--config", str(tmp_path / "missing.yaml")]
        )
        assert result.exit_code == 2

    def test_json_output_valid(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".promptgenie.yaml").write_text(
                "workspace:\n  name: proj\n", encoding="utf-8"
            )
            result = runner.invoke(cli, ["config", "validate", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True
        assert data["errors"] == []

    def test_json_output_invalid(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".promptgenie.yaml").write_text(
                "bad_key: 123\n", encoding="utf-8"
            )
            result = runner.invoke(cli, ["config", "validate", "--format", "json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_json_output_includes_warnings(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".promptgenie.yaml").write_text(
                "workspace:\n  name: ''\n", encoding="utf-8"
            )
            result = runner.invoke(cli, ["config", "validate", "--format", "json"])
        data = json.loads(result.output)
        assert len(data["warnings"]) > 0

    def test_type_error_shows_in_output(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".promptgenie.yaml").write_text(
                "security:\n  airgap: maybe\n", encoding="utf-8"
            )
            result = runner.invoke(cli, ["config", "validate"])
        assert result.exit_code == 1
        assert "airgap" in result.output

    def test_routing_rule_missing_provider_shows_error(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".promptgenie.yaml").write_text(
                "routing:\n  rules:\n    - if: \"*\"\n", encoding="utf-8"
            )
            result = runner.invoke(cli, ["config", "validate"])
        assert result.exit_code == 1
        assert "provider" in result.output


# ---------------------------------------------------------------------------
# config init command
# ---------------------------------------------------------------------------


class TestConfigInitCommand:
    def test_creates_file(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["config", "init"])
            assert result.exit_code == 0, result.output
            assert Path(".promptgenie.yaml").exists()

    def test_created_file_is_valid_yaml(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["config", "init"])
            content = Path(".promptgenie.yaml").read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)

    def test_created_file_contains_schema_pointer(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["config", "init"])
            content = Path(".promptgenie.yaml").read_text(encoding="utf-8")
        assert "promptgenie.dev/schemas/workspace.schema.json" in content

    def test_custom_name_written_into_file(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["config", "init", "--name", "myworkspace"])
            content = Path(".promptgenie.yaml").read_text(encoding="utf-8")
        assert "myworkspace" in content

    def test_refuses_to_overwrite_without_force(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".promptgenie.yaml").write_text("existing: true\n", encoding="utf-8")
            result = runner.invoke(cli, ["config", "init"])
        assert result.exit_code != 0
        assert "force" in result.output.lower() or "already exists" in result.output.lower()

    def test_force_overwrites_existing(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".promptgenie.yaml").write_text("existing: true\n", encoding="utf-8")
            result = runner.invoke(cli, ["config", "init", "--force"])
            assert result.exit_code == 0
            content = Path(".promptgenie.yaml").read_text(encoding="utf-8")
            assert "existing" not in content

    def test_init_output_is_valid_by_validate(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["config", "init", "--name", "testproj"])
            result = runner.invoke(cli, ["config", "validate", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["valid"] is True
        assert data["errors"] == []

    def test_yaml_language_server_comment_present(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["config", "init"])
            content = Path(".promptgenie.yaml").read_text(encoding="utf-8")
        assert "yaml-language-server" in content


# ---------------------------------------------------------------------------
# config show updated to include workspace / defaults
# ---------------------------------------------------------------------------


class TestConfigShowUpdated:
    def test_show_includes_schema_file_path(self, tmp_path):
        runner = CliRunner()
        schema_file = Path(__file__).parent.parent / "promptgenie" / "schemas" / "workspace.schema.json"
        assert schema_file.exists(), f"Schema file not found: {schema_file}"

    def test_workspace_schema_file_is_valid_json(self):
        schema_path = (
            Path(__file__).parent.parent / "promptgenie" / "schemas" / "workspace.schema.json"
        )
        assert schema_path.exists()
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        assert data.get("title") == "PromptGenie Workspace Configuration"
        assert "$defs" in data
        assert "Workspace" in data["$defs"]
        assert "Defaults" in data["$defs"]
        assert "Scanner" in data["$defs"]
        assert "Linter" in data["$defs"]
        assert "Routing" in data["$defs"]
        assert "Security" in data["$defs"]
        assert "AllowlistEntry" in data["$defs"]
        assert "CustomScanRule" in data["$defs"]
        assert "CustomLintRule" in data["$defs"]

    def test_schema_additionalProperties_false_everywhere(self):
        schema_path = (
            Path(__file__).parent.parent / "promptgenie" / "schemas" / "workspace.schema.json"
        )
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        assert data.get("additionalProperties") is False
        for def_name, def_schema in data["$defs"].items():
            if def_schema.get("type") == "object":
                assert def_schema.get("additionalProperties") is False, (
                    f"$defs.{def_name} is missing additionalProperties: false"
                )
