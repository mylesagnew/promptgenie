"""Tests for the NousResearch Hermes integration (profile + provider + cost)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.evaluator import estimate_cost
from promptgenie.core.generator import infer_target, load_profile
from promptgenie.core.providers import _default_providers, load_providers_config
from promptgenie.models import Profile

A_PROMPT = """## Objective
Summarise the changes in this diff for Claude.

## Output Format
A bullet list.
"""


# ---------------------------------------------------------------------------
# Target profile
# ---------------------------------------------------------------------------

class TestHermesProfile:
    def test_profile_loads(self):
        data = load_profile("hermes")
        assert data["name"] == "Hermes"
        assert data["category"] == "general-assistant"

    def test_profile_validates_clean(self):
        data = load_profile("hermes")
        errors, _warnings = Profile.from_dict(data, "hermes").validate()
        assert errors == [], errors

    def test_profile_has_safety_controls(self):
        # Hermes is steerable / lightly moderated — the profile must carry
        # external-guardrail guidance.
        data = load_profile("hermes")
        assert data.get("security_controls"), "Hermes profile should define security_controls"


# ---------------------------------------------------------------------------
# Target inference + generate/adapt
# ---------------------------------------------------------------------------

class TestHermesTargeting:
    def test_infer_target_hermes(self):
        assert infer_target("write a prompt for nous hermes") == "hermes"

    def test_generate_with_hermes_target(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["generate", "--no-config", "--no-lint", "--no-scan",
             "--target", "hermes", "summarise this log file"],
        )
        assert result.exit_code == 0

    def test_adapt_to_hermes(self):
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write(A_PROMPT)
            path = tmp.name
        result = runner.invoke(cli, ["adapt", path, "--from", "claude", "--to", "hermes"])
        assert result.exit_code == 0
        Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Provider + cost
# ---------------------------------------------------------------------------

class TestHermesProvider:
    def test_hermes_in_default_providers(self):
        provs = _default_providers()
        assert "hermes" in provs
        cfg = provs["hermes"]
        assert cfg.type == "openai_compat"
        assert cfg.base_url == "https://inference-api.nousresearch.com/v1"
        assert cfg.api_key_env == "NOUS_API_KEY"
        assert cfg.default_model.lower().startswith("hermes")

    def test_hermes_capabilities(self):
        cfg = _default_providers()["hermes"]
        assert cfg.capabilities.supports_tools is True
        assert cfg.capabilities.structured_output is True
        assert cfg.capabilities.max_context_tokens >= 128_000

    def test_hermes_resolvable_via_config(self):
        # When no user providers.yaml exists, the defaults back the loader.
        provs = load_providers_config()
        assert "hermes" in provs

    def test_hermes_cost_estimate_nonzero(self):
        cost = estimate_cost("Hermes-4-405B", 1_000_000, 1_000_000)
        assert cost > 0.0

    def test_unknown_model_still_zero(self):
        assert estimate_cost("totally-unknown-model", 1000, 1000) == 0.0
