"""providers.py — Provider protocol and built-in provider adapters.

Provider protocol
-----------------
Every provider must implement two async methods::

    async def complete(messages, *, model, max_tokens, timeout, **kw) -> str
    async def stream(messages, *, model, max_tokens, timeout, **kw) -> AsyncIterator[str]

Where ``messages`` is a list of dicts with ``role`` and ``content`` keys.

Built-in providers
------------------
  AnthropicProvider     — Claude models via Anthropic Messages API
  OpenAICompatProvider  — Any OpenAI-compatible endpoint (OpenAI, Ollama,
                          LocalAI, LM Studio, vLLM)

Provider config (``~/.config/promptgenie/providers.yaml``)::

    providers:
      ollama:
        type: openai_compat
        base_url: http://localhost:11434/v1
        default_model: llama3
        local: true

      my-openai:
        type: openai_compat
        base_url: https://api.openai.com/v1
        api_key_env: OPENAI_API_KEY
        default_model: gpt-4o

      claude:
        type: anthropic
        api_key_env: ANTHROPIC_API_KEY
        default_model: claude-opus-4-5

Public API
----------
  ``load_providers_config()``       → dict[str, ProviderConfig]
  ``get_provider(name)``            → Provider instance
  ``add_provider(name, config)``    → persist to providers.yaml
  ``ProviderCapabilities``          — dataclass with feature flags
  ``ProviderConfig``                — dataclass for a config entry
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from promptgenie.core.errors import EXIT_PROVIDER, EXIT_TIMEOUT, PromptGenieError

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path("~/.config/promptgenie").expanduser()
_PROVIDERS_FILE = _CONFIG_DIR / "providers.yaml"

# ---------------------------------------------------------------------------
# Capabilities & Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProviderCapabilities:
    streaming: bool = True
    structured_output: bool = False
    max_context_tokens: int = 8192
    local: bool = False
    supports_tools: bool = False


@dataclass
class ProviderConfig:
    name: str
    type: str  # "anthropic" | "openai_compat"
    base_url: str = ""
    api_key_env: str = ""
    api_key: str = ""  # direct value (not recommended — use api_key_env)
    default_model: str = ""
    local: bool = False
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Config loader / saver
# ---------------------------------------------------------------------------


def load_providers_config() -> dict[str, ProviderConfig]:
    """Return all configured providers keyed by name."""
    if not _PROVIDERS_FILE.exists():
        return _default_providers()

    raw = yaml.safe_load(_PROVIDERS_FILE.read_text(encoding="utf-8")) or {}
    providers_raw = raw.get("providers", {})
    result: dict[str, ProviderConfig] = {}
    for name, cfg in providers_raw.items():
        if not isinstance(cfg, dict):
            continue
        cap_raw = cfg.get("capabilities", {}) or {}
        cap = ProviderCapabilities(
            streaming=bool(cap_raw.get("streaming", True)),
            structured_output=bool(cap_raw.get("structured_output", False)),
            max_context_tokens=int(cap_raw.get("max_context_tokens", 8192)),
            local=bool(cap_raw.get("local", cfg.get("local", False))),
            supports_tools=bool(cap_raw.get("supports_tools", False)),
        )
        result[name] = ProviderConfig(
            name=name,
            type=str(cfg.get("type", "openai_compat")),
            base_url=str(cfg.get("base_url", "")),
            api_key_env=str(cfg.get("api_key_env", "")),
            api_key=str(cfg.get("api_key", "")),
            default_model=str(cfg.get("default_model", "")),
            local=bool(cfg.get("local", False)),
            capabilities=cap,
            extra={
                k: v
                for k, v in cfg.items()
                if k
                not in (
                    "type",
                    "base_url",
                    "api_key_env",
                    "api_key",
                    "default_model",
                    "local",
                    "capabilities",
                )
            },
        )
    return result


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "anthropic": ProviderConfig(
            name="anthropic",
            type="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            default_model="claude-opus-4-5",
            capabilities=ProviderCapabilities(
                streaming=True,
                structured_output=True,
                max_context_tokens=200_000,
                supports_tools=True,
            ),
        ),
        "openai": ProviderConfig(
            name="openai",
            type="openai_compat",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            default_model="gpt-4o",
            capabilities=ProviderCapabilities(
                streaming=True,
                structured_output=True,
                max_context_tokens=128_000,
                supports_tools=True,
            ),
        ),
        "ollama": ProviderConfig(
            name="ollama",
            type="openai_compat",
            base_url="http://localhost:11434/v1",
            default_model="llama3",
            local=True,
            capabilities=ProviderCapabilities(
                streaming=True,
                local=True,
                max_context_tokens=8192,
            ),
        ),
    }


def save_providers_config(providers: dict[str, ProviderConfig]) -> None:
    """Persist providers dict to ~/.config/promptgenie/providers.yaml."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {"providers": {}}
    for name, cfg in providers.items():
        entry: dict[str, Any] = {"type": cfg.type}
        if cfg.base_url:
            entry["base_url"] = cfg.base_url
        if cfg.api_key_env:
            entry["api_key_env"] = cfg.api_key_env
        if cfg.default_model:
            entry["default_model"] = cfg.default_model
        if cfg.local:
            entry["local"] = cfg.local
        if cfg.capabilities:
            entry["capabilities"] = {
                "streaming": cfg.capabilities.streaming,
                "structured_output": cfg.capabilities.structured_output,
                "max_context_tokens": cfg.capabilities.max_context_tokens,
                "local": cfg.capabilities.local,
                "supports_tools": cfg.capabilities.supports_tools,
            }
        entry.update(cfg.extra)
        out["providers"][name] = entry
    _PROVIDERS_FILE.write_text(
        yaml.dump(out, default_flow_style=False, sort_keys=False), encoding="utf-8"
    )


def add_provider(name: str, provider_type: str, **kwargs: Any) -> ProviderConfig:
    """Add or update a provider entry and save to disk."""
    providers = load_providers_config()
    cap = ProviderCapabilities(
        local=bool(kwargs.get("local", False)),
    )
    cfg = ProviderConfig(
        name=name,
        type=provider_type,
        base_url=str(kwargs.get("base_url", "")),
        api_key_env=str(kwargs.get("api_key_env", "")),
        default_model=str(kwargs.get("default_model", "")),
        local=bool(kwargs.get("local", False)),
        capabilities=cap,
    )
    providers[name] = cfg
    save_providers_config(providers)
    return cfg


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


def get_provider(name: str, model_override: str | None = None) -> BaseProvider:
    """Return a Provider instance for *name*.

    Raises PromptGenieError if the provider is unknown or blocked by air-gap mode.
    """
    # ── Air-gap check ─────────────────────────────────────────────────────────
    try:
        from promptgenie.core.config import load_config
        cfg_pg = load_config()
        if cfg_pg.security.airgap:
            _local_names = {"ollama", "localai", "lm-studio", "lmstudio", "vllm", "llamafile"}
            if name.lower() not in _local_names:
                raise PromptGenieError(
                    f"Air-gap mode is enabled — external provider '{name}' is blocked.",
                    code=EXIT_PROVIDER,
                    hint=(
                        "Air-gap mode only permits local providers (Ollama, LocalAI, etc.). "
                        "Disable with: promptgenie config set security.airgap false"
                    ),
                )
    except PromptGenieError:
        raise
    except Exception:
        pass  # config load failure — don't block

    configs = load_providers_config()
    if name not in configs:
        raise PromptGenieError(
            f"Unknown provider {name!r}. Run 'promptgenie provider list' to see available providers.",
            code=EXIT_PROVIDER,
            hint=f"Add it with: promptgenie provider add {name} --type openai_compat --base-url <url>",
        )
    cfg = configs[name]
    model = model_override or cfg.default_model
    if cfg.type == "anthropic":
        return AnthropicProvider(cfg, model=model)
    return OpenAICompatProvider(cfg, model=model)


# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------


class BaseProvider:
    """Shared helpers for all provider implementations."""

    def __init__(self, config: ProviderConfig, model: str = "") -> None:
        self.config = config
        self.model = model or config.default_model

    def _resolve_api_key(self) -> str:
        if self.config.api_key:
            return self.config.api_key
        if self.config.api_key_env:
            key = os.environ.get(self.config.api_key_env, "")
            if not key:
                raise PromptGenieError(
                    f"Provider '{self.config.name}' requires API key in "
                    f"env var {self.config.api_key_env!r} but it is not set.",
                    code=EXIT_PROVIDER,
                    hint=f"export {self.config.api_key_env}=your-key",
                )
            return key
        return ""

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        raise NotImplementedError

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        timeout: int = 120,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # make this a generator


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


class AnthropicProvider(BaseProvider):
    """Claude via Anthropic Messages API.

    Prefers the ``anthropic`` Python SDK when installed; falls back to
    raw httpx requests otherwise.
    """

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        m = model or self.model
        system_msgs = [msg["content"] for msg in messages if msg["role"] == "system"]
        user_msgs = [msg for msg in messages if msg["role"] != "system"]
        system_text = "\n\n".join(system_msgs) if system_msgs else None

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self._resolve_api_key())
            kwargs_build: dict[str, Any] = {
                "model": m,
                "max_tokens": max_tokens,
                "messages": user_msgs,
            }
            if system_text:
                kwargs_build["system"] = system_text
            response = await asyncio.wait_for(
                client.messages.create(**kwargs_build), timeout=timeout
            )
            return str(response.content[0].text)
        except ImportError:
            return await self._complete_httpx(user_msgs, system_text, m, max_tokens, timeout)
        except asyncio.TimeoutError as exc:
            raise PromptGenieError("Anthropic API call timed out.", code=EXIT_TIMEOUT) from exc
        except Exception as exc:
            raise PromptGenieError(
                f"Anthropic API error: {type(exc).__name__}", code=EXIT_PROVIDER
            ) from exc

    async def _complete_httpx(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        model: str,
        max_tokens: int,
        timeout: int,
    ) -> str:
        try:
            import httpx
        except ImportError as exc:
            raise PromptGenieError(
                "Neither 'anthropic' nor 'httpx' is installed. "
                "pip install anthropic  OR  pip install httpx",
                code=EXIT_PROVIDER,
            ) from exc

        headers = {
            "x-api-key": self._resolve_api_key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
            )
        resp.raise_for_status()
        return str(resp.json()["content"][0]["text"])

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        timeout: int = 120,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        m = model or self.model
        system_msgs = [msg["content"] for msg in messages if msg["role"] == "system"]
        user_msgs = [msg for msg in messages if msg["role"] != "system"]
        system_text = "\n\n".join(system_msgs) if system_msgs else None

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self._resolve_api_key())
            kwargs_build: dict[str, Any] = {
                "model": m,
                "max_tokens": max_tokens,
                "messages": user_msgs,
            }
            if system_text:
                kwargs_build["system"] = system_text
            async with client.messages.stream(**kwargs_build) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    yield text
        except ImportError:
            # Fallback: non-streaming complete, yield all at once
            text = await self._complete_httpx(user_msgs, system_text, m, max_tokens, timeout)
            yield text
        except Exception as exc:
            raise PromptGenieError(
                f"Anthropic stream error: {type(exc).__name__}", code=EXIT_PROVIDER
            ) from exc


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (OpenAI, Ollama, LocalAI, LM Studio, vLLM)
# ---------------------------------------------------------------------------


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _validate_provider_base_url(cfg: ProviderConfig) -> str:
    """Validate and normalise a provider ``base_url`` (V-004, CWE-319).

    Rules:
      * Empty -> default ``https://api.openai.com/v1``.
      * Only ``http``/``https`` schemes are accepted.
      * Plain ``http://`` is only permitted when the host is loopback
        (``localhost``/``127.0.0.1``/``::1``) OR the provider is marked
        ``local: true`` AND no API key is configured. This prevents sending an
        ``Authorization`` header in cleartext to a remote endpoint.

    Returns the base_url with any trailing ``/`` stripped.
    """
    from urllib.parse import urlsplit

    raw = (cfg.base_url or "").strip()
    if not raw:
        return "https://api.openai.com/v1"

    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise PromptGenieError(
            f"Provider '{cfg.name}' base_url uses unsupported scheme {scheme!r}: {raw!r}",
            code=EXIT_PROVIDER,
            hint="Use an https:// endpoint (or http:// only for a local loopback dev server).",
        )

    if scheme == "http":
        host = (parts.hostname or "").lower()
        is_loopback = host in _LOOPBACK_HOSTS
        has_key = bool(cfg.api_key_env or cfg.api_key)
        # Allow http only for loopback hosts, OR for an explicitly-local provider
        # that has no API key (a keyless local dev server). Anything else would
        # risk leaking credentials over cleartext.
        if not (is_loopback or (cfg.local and not has_key)):
            raise PromptGenieError(
                f"Provider '{cfg.name}' base_url uses cleartext http:// to a "
                f"non-loopback host {host!r}: {raw!r}",
                code=EXIT_PROVIDER,
                hint=(
                    "Use https:// for remote endpoints. Plain http:// is only allowed "
                    "for loopback hosts (localhost/127.0.0.1/::1) or a keyless local "
                    "provider, to avoid sending the API key in cleartext."
                ),
            )

    return raw.rstrip("/")


class OpenAICompatProvider(BaseProvider):
    """Covers any OpenAI-chat-completions-compatible endpoint."""

    def _base_url(self) -> str:
        return _validate_provider_base_url(self.config)

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = ""
        if self.config.api_key_env or self.config.api_key:
            import contextlib

            with contextlib.suppress(PromptGenieError):  # local providers (Ollama) don't need a key
                key = self._resolve_api_key()
        if key:
            headers["authorization"] = f"Bearer {key}"
        return headers

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        try:
            import httpx
        except ImportError as exc:
            raise PromptGenieError(
                "httpx is required for OpenAI-compatible providers. pip install httpx",
                code=EXIT_PROVIDER,
            ) from exc

        m = model or self.model
        body = {"model": m, "messages": messages, "max_tokens": max_tokens, "stream": False}
        body.update(kwargs)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self._base_url()}/chat/completions",
                    headers=self._headers(),
                    json=body,
                )
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"])
        except asyncio.TimeoutError as exc:
            raise PromptGenieError(
                f"Provider '{self.config.name}' timed out.", code=EXIT_TIMEOUT
            ) from exc
        except Exception as exc:
            raise PromptGenieError(
                f"Provider '{self.config.name}' error: {type(exc).__name__}", code=EXIT_PROVIDER
            ) from exc

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 2048,
        timeout: int = 120,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        try:
            import httpx
        except ImportError as exc:
            raise PromptGenieError(
                "httpx is required for OpenAI-compatible providers. pip install httpx",
                code=EXIT_PROVIDER,
            ) from exc

        m = model or self.model
        body = {"model": m, "messages": messages, "max_tokens": max_tokens, "stream": True}
        body.update(kwargs)

        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream(
                    "POST",
                    f"{self._base_url()}/chat/completions",
                    headers=self._headers(),
                    json=body,
                ) as resp,
            ):
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except PromptGenieError:
            raise
        except Exception as exc:
            raise PromptGenieError(
                f"Provider '{self.config.name}' stream error: {type(exc).__name__}",
                code=EXIT_PROVIDER,
            ) from exc


# ---------------------------------------------------------------------------
# Doctor — reachability check
# ---------------------------------------------------------------------------


async def probe_provider(name: str) -> tuple[bool, str]:
    """Test reachability of *name*. Returns (ok, message)."""
    configs = load_providers_config()
    if name not in configs:
        return False, f"Provider '{name}' not configured."
    cfg = configs[name]

    if cfg.type == "anthropic":
        key = os.environ.get(cfg.api_key_env or "ANTHROPIC_API_KEY", "")
        if not key:
            return False, f"API key env var {cfg.api_key_env or 'ANTHROPIC_API_KEY'} not set."
        return True, "API key present (not verified — would incur cost)."

    # OpenAI-compat: hit /models endpoint
    try:
        import httpx

        headers = {"content-type": "application/json"}
        key = os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else ""
        if key:
            headers["authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{cfg.base_url}/models", headers=headers)
        if resp.status_code < 400:
            return True, f"Reachable at {cfg.base_url} (HTTP {resp.status_code})."
        return False, f"HTTP {resp.status_code} from {cfg.base_url}/models."
    except ImportError:
        return False, "httpx not installed — cannot probe."
    except Exception as exc:
        return False, f"Connection failed: {type(exc).__name__}"
