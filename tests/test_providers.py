"""Tests for promptgenie.core.providers."""

from __future__ import annotations

import pytest
import yaml

from promptgenie.core.errors import PromptGenieError
from promptgenie.core.providers import (
    ProviderCapabilities,
    ProviderConfig,
    _default_providers,
    _validate_provider_base_url,
    add_provider,
    get_provider,
    load_providers_config,
    save_providers_config,
)

# ---------------------------------------------------------------------------
# ProviderCapabilities
# ---------------------------------------------------------------------------


class TestProviderCapabilities:
    def test_defaults(self):
        cap = ProviderCapabilities()
        assert cap.streaming is True
        assert cap.local is False
        assert cap.max_context_tokens == 8192

    def test_custom_values(self):
        cap = ProviderCapabilities(
            streaming=False,
            local=True,
            max_context_tokens=200_000,
            supports_tools=True,
            structured_output=True,
        )
        assert cap.local is True
        assert cap.max_context_tokens == 200_000


# ---------------------------------------------------------------------------
# default providers
# ---------------------------------------------------------------------------


class TestDefaultProviders:
    def test_has_anthropic(self):
        providers = _default_providers()
        assert "anthropic" in providers

    def test_has_openai(self):
        providers = _default_providers()
        assert "openai" in providers

    def test_has_ollama(self):
        providers = _default_providers()
        assert "ollama" in providers

    def test_ollama_is_local(self):
        providers = _default_providers()
        assert providers["ollama"].local is True
        assert "localhost" in providers["ollama"].base_url


# ---------------------------------------------------------------------------
# load_providers_config
# ---------------------------------------------------------------------------


class TestLoadProvidersConfig:
    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as prov_mod

        monkeypatch.setattr(prov_mod, "_PROVIDERS_FILE", tmp_path / "no_such.yaml")
        result = load_providers_config()
        assert "anthropic" in result

    def test_loads_from_yaml(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as prov_mod

        config_file = tmp_path / "providers.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "providers": {
                        "my-ollama": {
                            "type": "openai_compat",
                            "base_url": "http://localhost:11434/v1",
                            "default_model": "llama3",
                            "local": True,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(prov_mod, "_PROVIDERS_FILE", config_file)
        result = load_providers_config()
        assert "my-ollama" in result
        assert result["my-ollama"].local is True
        assert result["my-ollama"].default_model == "llama3"


# ---------------------------------------------------------------------------
# save_providers_config / add_provider
# ---------------------------------------------------------------------------


class TestSaveProviders:
    def test_save_and_reload(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as prov_mod

        config_file = tmp_path / "providers.yaml"
        monkeypatch.setattr(prov_mod, "_PROVIDERS_FILE", config_file)
        monkeypatch.setattr(prov_mod, "_CONFIG_DIR", tmp_path)

        providers = {
            "test": ProviderConfig(
                name="test",
                type="openai_compat",
                base_url="http://localhost:8080/v1",
                default_model="gpt-test",
            )
        }
        save_providers_config(providers)
        assert config_file.exists()

        reloaded = load_providers_config()
        assert "test" in reloaded
        assert reloaded["test"].base_url == "http://localhost:8080/v1"

    def test_add_provider(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as prov_mod

        config_file = tmp_path / "providers.yaml"
        monkeypatch.setattr(prov_mod, "_PROVIDERS_FILE", config_file)
        monkeypatch.setattr(prov_mod, "_CONFIG_DIR", tmp_path)

        cfg = add_provider(
            "lm-studio",
            provider_type="openai_compat",
            base_url="http://localhost:1234/v1",
            default_model="local-model",
            local=True,
        )
        assert cfg.name == "lm-studio"
        assert cfg.local is True


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------


class TestGetProvider:
    def test_unknown_provider_raises(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as prov_mod

        monkeypatch.setattr(prov_mod, "_PROVIDERS_FILE", tmp_path / "no_such.yaml")
        with pytest.raises(PromptGenieError) as exc_info:
            get_provider("nonexistent-xyz")
        assert "Unknown provider" in str(exc_info.value)

    def test_returns_anthropic_provider(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as prov_mod

        monkeypatch.setattr(prov_mod, "_PROVIDERS_FILE", tmp_path / "no_such.yaml")
        provider = get_provider("anthropic")
        assert hasattr(provider, "complete")
        assert hasattr(provider, "stream")

    def test_model_override(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as prov_mod

        monkeypatch.setattr(prov_mod, "_PROVIDERS_FILE", tmp_path / "no_such.yaml")
        provider = get_provider("anthropic", model_override="claude-haiku-3-5")
        assert provider.model == "claude-haiku-3-5"

    def test_returns_openai_compat_for_ollama(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as prov_mod
        from promptgenie.core.providers import OpenAICompatProvider

        monkeypatch.setattr(prov_mod, "_PROVIDERS_FILE", tmp_path / "no_such.yaml")
        provider = get_provider("ollama")
        assert isinstance(provider, OpenAICompatProvider)


# ---------------------------------------------------------------------------
# V-004: provider base_url TLS / scheme validation (CWE-319)
# ---------------------------------------------------------------------------


class TestV004ProviderBaseUrlValidation:
    def test_empty_defaults_to_openai_https(self):
        cfg = ProviderConfig(name="x", type="openai_compat", base_url="")
        assert _validate_provider_base_url(cfg) == "https://api.openai.com/v1"

    def test_https_allowed(self):
        cfg = ProviderConfig(name="x", type="openai_compat", base_url="https://api.example.com/v1/")
        assert _validate_provider_base_url(cfg) == "https://api.example.com/v1"

    def test_remote_http_with_key_rejected(self):
        cfg = ProviderConfig(
            name="x",
            type="openai_compat",
            base_url="http://api.example.com/v1",
            api_key_env="OPENAI_API_KEY",
        )
        with pytest.raises(PromptGenieError):
            _validate_provider_base_url(cfg)

    def test_remote_http_without_key_rejected(self):
        # Non-loopback, non-local: cleartext http is refused even keyless.
        cfg = ProviderConfig(name="x", type="openai_compat", base_url="http://api.example.com/v1")
        with pytest.raises(PromptGenieError):
            _validate_provider_base_url(cfg)

    def test_loopback_http_keyless_allowed(self):
        cfg = ProviderConfig(
            name="ollama", type="openai_compat", base_url="http://localhost:11434/v1", local=True
        )
        assert _validate_provider_base_url(cfg) == "http://localhost:11434/v1"

    def test_loopback_ip_http_allowed(self):
        cfg = ProviderConfig(name="x", type="openai_compat", base_url="http://127.0.0.1:8080/v1")
        assert _validate_provider_base_url(cfg) == "http://127.0.0.1:8080/v1"

    def test_loopback_http_with_key_allowed(self):
        # Loopback is trusted even with a key (key never leaves the host).
        cfg = ProviderConfig(
            name="x",
            type="openai_compat",
            base_url="http://localhost:11434/v1",
            api_key="secret",
        )
        assert _validate_provider_base_url(cfg) == "http://localhost:11434/v1"

    def test_local_http_with_key_rejected(self):
        # local: true but a key is configured and host is not loopback -> reject.
        cfg = ProviderConfig(
            name="x",
            type="openai_compat",
            base_url="http://lan-host:11434/v1",
            local=True,
            api_key="secret",
        )
        with pytest.raises(PromptGenieError):
            _validate_provider_base_url(cfg)

    def test_bad_scheme_rejected(self):
        cfg = ProviderConfig(name="x", type="openai_compat", base_url="ftp://api.example.com/v1")
        with pytest.raises(PromptGenieError):
            _validate_provider_base_url(cfg)
