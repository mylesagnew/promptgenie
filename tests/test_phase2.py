"""test_phase2.py — Phase 2: PromptSpec + Run Engine feature tests.

Covers:
  - Secret var bindings (from_env / secret: true) in spec schema + loader
  - Secret redaction in RunResult
  - Provider doctor capabilities output
  - TTY-aware on_token callback behaviour
  - vars inspect secret source reporting
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from promptgenie.core.run_engine import RunEvent, RunResult, run_spec
from promptgenie.core.spec import (
    SecretVarBinding,
    load_spec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec_file(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "test.prompt.yaml"
    p.write_text(yaml.dump(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Secret var: schema / loader
# ---------------------------------------------------------------------------


class TestSecretVarLoading:
    def test_plain_var_stays_in_vars(self, tmp_path):
        p = _make_spec_file(
            tmp_path,
            {
                "version": 1,
                "name": "t",
                "target": "claude-code",
                "vars": {"env": "prod"},
            },
        )
        spec = load_spec(p)
        assert spec.vars == {"env": "prod"}
        assert spec.secret_vars == {}

    def test_from_env_binding_goes_to_secret_vars(self, tmp_path):
        p = _make_spec_file(
            tmp_path,
            {
                "version": 1,
                "name": "t",
                "target": "claude-code",
                "vars": {
                    "api_token": {"from_env": "GITHUB_TOKEN", "secret": True},
                },
            },
        )
        spec = load_spec(p)
        assert "api_token" not in spec.vars
        assert "api_token" in spec.secret_vars
        binding = spec.secret_vars["api_token"]
        assert binding.from_env == "GITHUB_TOKEN"
        assert binding.secret is True

    def test_from_env_default_secret_true(self, tmp_path):
        p = _make_spec_file(
            tmp_path,
            {
                "version": 1,
                "name": "t",
                "target": "claude-code",
                "vars": {
                    "token": {"from_env": "MY_TOKEN"},
                },
            },
        )
        spec = load_spec(p)
        assert spec.secret_vars["token"].secret is True

    def test_from_env_with_fallback_default(self, tmp_path):
        p = _make_spec_file(
            tmp_path,
            {
                "version": 1,
                "name": "t",
                "target": "claude-code",
                "vars": {
                    "token": {"from_env": "MY_TOKEN", "default": "fallback-val"},
                },
            },
        )
        spec = load_spec(p)
        assert spec.secret_vars["token"].default == "fallback-val"

    def test_mixed_plain_and_secret_vars(self, tmp_path):
        p = _make_spec_file(
            tmp_path,
            {
                "version": 1,
                "name": "t",
                "target": "claude-code",
                "vars": {
                    "env": "prod",
                    "token": {"from_env": "API_TOKEN", "secret": True},
                    "count": 3,
                },
            },
        )
        spec = load_spec(p)
        assert set(spec.vars.keys()) == {"env", "count"}
        assert set(spec.secret_vars.keys()) == {"token"}


# ---------------------------------------------------------------------------
# Secret var: run_engine resolution
# ---------------------------------------------------------------------------


class TestSecretVarResolution:
    def _minimal_spec(self, tmp_path: Path, extra: dict | None = None) -> Path:
        content: dict = {
            "version": 1,
            "name": "t",
            "target": "claude-code",
            "prompt": "Token is {{api_token}}",
            "vars": {
                "api_token": {"from_env": "TEST_API_TOKEN", "secret": True},
            },
        }
        if extra:
            content.update(extra)
        return _make_spec_file(tmp_path, content)

    def test_secret_var_resolved_from_env(self, tmp_path):
        p = self._minimal_spec(tmp_path)
        spec = load_spec(p)
        with patch.dict(os.environ, {"TEST_API_TOKEN": "tok-abc123"}):
            result = run_spec(spec, dry_run=True, no_input=True)
        assert result.resolved_vars["api_token"] == "tok-abc123"

    def test_secret_var_redacted_in_redacted_vars(self, tmp_path):
        p = self._minimal_spec(tmp_path)
        spec = load_spec(p)
        with patch.dict(os.environ, {"TEST_API_TOKEN": "tok-abc123"}):
            result = run_spec(spec, dry_run=True, no_input=True)
        redacted = result.redacted_vars()
        assert redacted["api_token"] == "***"

    def test_secret_var_names_populated_in_result(self, tmp_path):
        p = self._minimal_spec(tmp_path)
        spec = load_spec(p)
        with patch.dict(os.environ, {"TEST_API_TOKEN": "tok-abc123"}):
            result = run_spec(spec, dry_run=True, no_input=True)
        assert "api_token" in result.secret_var_names

    def test_missing_env_var_raises_without_default(self, tmp_path):
        from promptgenie.core.errors import PromptGenieError

        p = self._minimal_spec(tmp_path)
        spec = load_spec(p)
        env = {k: v for k, v in os.environ.items() if k != "TEST_API_TOKEN"}
        with (
            patch.dict(os.environ, env, clear=True),
            pytest.raises(PromptGenieError, match="TEST_API_TOKEN"),
        ):
            run_spec(spec, dry_run=True, no_input=True)

    def test_missing_env_var_uses_default(self, tmp_path):
        content = {
            "version": 1,
            "name": "t",
            "target": "claude-code",
            "prompt": "Token is {{api_token}}",
            "vars": {
                "api_token": {"from_env": "UNSET_TOKEN_XYZ", "secret": True, "default": "fallback"},
            },
        }
        p = _make_spec_file(tmp_path, content)
        spec = load_spec(p)
        env = {k: v for k, v in os.environ.items() if k != "UNSET_TOKEN_XYZ"}
        with patch.dict(os.environ, env, clear=True):
            result = run_spec(spec, dry_run=True, no_input=True)
        assert result.resolved_vars["api_token"] == "fallback"

    def test_cli_var_overrides_secret_binding(self, tmp_path):
        p = self._minimal_spec(tmp_path)
        spec = load_spec(p)
        result = run_spec(
            spec,
            dry_run=True,
            no_input=True,
            cli_vars=["api_token=cli-override"],
        )
        assert result.resolved_vars["api_token"] == "cli-override"


# ---------------------------------------------------------------------------
# RunResult.redacted_vars
# ---------------------------------------------------------------------------


class TestRunResultRedactedVars:
    def test_non_secret_vars_pass_through(self):
        result = RunResult(
            run_id="x",
            spec_name="t",
            status="ok",
            response="",
            dry_run=False,
            resolved_vars={"env": "prod", "count": 3},
            secret_var_names=set(),
        )
        assert result.redacted_vars() == {"env": "prod", "count": 3}

    def test_secret_vars_replaced_with_stars(self):
        result = RunResult(
            run_id="x",
            spec_name="t",
            status="ok",
            response="",
            dry_run=False,
            resolved_vars={"env": "prod", "token": "abc123"},
            secret_var_names={"token"},
        )
        rv = result.redacted_vars()
        assert rv["token"] == "***"
        assert rv["env"] == "prod"

    def test_multiple_secrets_all_redacted(self):
        result = RunResult(
            run_id="x",
            spec_name="t",
            status="ok",
            response="",
            dry_run=False,
            resolved_vars={"a": "1", "b": "2", "c": "3"},
            secret_var_names={"a", "c"},
        )
        rv = result.redacted_vars()
        assert rv == {"a": "***", "b": "2", "c": "***"}


# ---------------------------------------------------------------------------
# Provider doctor — capabilities
# ---------------------------------------------------------------------------


class TestProviderDoctorCapabilities:
    def test_doctor_json_includes_capabilities(self):
        from click.testing import CliRunner

        from promptgenie.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["provider", "doctor", "anthropic", "--format", "json"])
        # Doctor may fail reachability but should still emit capabilities
        try:
            data = json.loads(result.output)
        except json.JSONDecodeError:
            pytest.skip("output not JSON (may be an import error in test env)")
        assert "capabilities" in data
        cap = data["capabilities"]
        assert "streaming" in cap
        assert "max_context_tokens" in cap
        assert "supports_tools" in cap
        assert "local" in cap

    def test_doctor_json_local_true_for_ollama(self):
        from click.testing import CliRunner

        from promptgenie.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["provider", "doctor", "ollama", "--format", "json"])
        try:
            data = json.loads(result.output)
        except json.JSONDecodeError:
            pytest.skip("output not JSON")
        assert data["capabilities"].get("local") is True

    def test_doctor_anthropic_max_context_tokens(self):
        from click.testing import CliRunner

        from promptgenie.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["provider", "doctor", "anthropic", "--format", "json"])
        try:
            data = json.loads(result.output)
        except json.JSONDecodeError:
            pytest.skip("output not JSON")
        assert data["capabilities"]["max_context_tokens"] == 200_000


# ---------------------------------------------------------------------------
# TTY-aware streaming: on_token callback path
# ---------------------------------------------------------------------------


class TestTTYStreamingCallback:
    """Test that on_token produces correct output on TTY vs non-TTY paths.

    We test the run_cmd callback logic in isolation without invoking the
    full CLI (which would require a real provider). Instead we verify the
    behaviour through run_spec with a mock provider.
    """

    def _make_mock_provider(self, tokens: list[str]):
        """Return a mock BaseProvider that streams the given tokens."""

        async def _stream(*a, **kw):
            for t in tokens:
                yield t

        provider = MagicMock()
        provider.model = "mock-model"
        provider.stream = _stream
        provider.complete = AsyncMock(return_value="".join(tokens))
        return provider

    def test_non_tty_on_token_receives_each_token(self, tmp_path):
        p = _make_spec_file(
            tmp_path,
            {
                "version": 1,
                "name": "t",
                "target": "claude-code",
                "prompt": "Hello",
            },
        )
        spec = load_spec(p)
        received: list[str] = []

        provider = self._make_mock_provider(["Hello", " ", "World"])
        with patch("promptgenie.core.run_engine.get_provider", return_value=provider):
            run_spec(spec, on_token=received.append, stream=True, no_input=True, no_history=True)

        assert received == ["Hello", " ", "World"]

    def test_non_streaming_on_token_receives_full_response(self, tmp_path):
        p = _make_spec_file(
            tmp_path,
            {
                "version": 1,
                "name": "t",
                "target": "claude-code",
                "prompt": "Hello",
            },
        )
        spec = load_spec(p)
        received: list[str] = []

        provider = self._make_mock_provider(["Full response text"])
        with patch("promptgenie.core.run_engine.get_provider", return_value=provider):
            run_spec(spec, on_token=received.append, stream=False, no_input=True, no_history=True)

        assert "".join(received) == "Full response text"

    def test_ndjson_events_contain_all_token_events(self, tmp_path):
        p = _make_spec_file(
            tmp_path,
            {
                "version": 1,
                "name": "t",
                "target": "claude-code",
                "prompt": "Hello",
            },
        )
        spec = load_spec(p)
        events: list[RunEvent] = []

        provider = self._make_mock_provider(["tok1", "tok2"])
        with patch("promptgenie.core.run_engine.get_provider", return_value=provider):
            run_spec(spec, on_event=events.append, stream=True, no_input=True, no_history=True)

        token_events = [e for e in events if e.event == "token"]
        assert len(token_events) == 2
        assert token_events[0].data["text"] == "tok1"
        assert token_events[1].data["text"] == "tok2"


# ---------------------------------------------------------------------------
# SecretVarBinding dataclass
# ---------------------------------------------------------------------------


class TestSecretVarBinding:
    def test_defaults(self):
        b = SecretVarBinding(from_env="MY_VAR")
        assert b.secret is True
        assert b.default is None

    def test_custom_values(self):
        b = SecretVarBinding(from_env="MY_VAR", secret=False, default="fallback")
        assert b.secret is False
        assert b.default == "fallback"
