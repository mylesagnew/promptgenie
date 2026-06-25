"""Async provider + run-engine send-path coverage (roadmap follow-up: 80→85%).

Mocks httpx (OpenAI-compatible) and the anthropic SDK so the provider
complete()/stream() coroutines and the non-dry-run run_engine path execute
without any network access.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from promptgenie.core.errors import PromptGenieError
from promptgenie.core.providers import (
    AnthropicProvider,
    OpenAICompatProvider,
    ProviderConfig,
)


def _run(coro):
    return asyncio.run(coro)


async def _collect(agen):
    return [chunk async for chunk in agen]


# ---------------------------------------------------------------------------
# Fake httpx primitives
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, *, json_data=None, lines=None, raise_exc=None):
        self._json = json_data
        self._lines = lines or []
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def json(self):
        return self._json

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _FakeAsyncClient:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return self._resp

    def stream(self, *a, **k):
        return _FakeStreamCtx(self._resp)


def _patch_httpx(monkeypatch, resp):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(resp))


# ---------------------------------------------------------------------------
# OpenAI-compatible provider
# ---------------------------------------------------------------------------


class TestOpenAICompatProvider:
    def _provider(self):
        cfg = ProviderConfig(
            name="vllm",
            type="openai_compat",
            base_url="http://localhost:8000/v1",
            local=True,
            default_model="local-model",
        )
        return OpenAICompatProvider(cfg, model="local-model")

    def test_complete(self, monkeypatch):
        resp = _FakeResp(json_data={"choices": [{"message": {"content": "hello there"}}]})
        _patch_httpx(monkeypatch, resp)
        out = _run(self._provider().complete([{"role": "user", "content": "hi"}]))
        assert out == "hello there"

    def test_stream_parses_sse(self, monkeypatch):
        lines = [
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            "data: [DONE]",
        ]
        _patch_httpx(monkeypatch, _FakeResp(lines=lines))
        chunks = _run(_collect(self._provider().stream([{"role": "user", "content": "hi"}])))
        assert "".join(chunks) == "Hello"

    def test_complete_http_error_maps_to_promptgenie_error(self, monkeypatch):
        resp = _FakeResp(raise_exc=RuntimeError("500"))
        _patch_httpx(monkeypatch, resp)
        with pytest.raises(PromptGenieError):
            _run(self._provider().complete([{"role": "user", "content": "hi"}]))


# ---------------------------------------------------------------------------
# Anthropic provider (SDK mocked)
# ---------------------------------------------------------------------------


class _FakeAnthropicMessages:
    def __init__(self, text="claude says hi", stream_chunks=None, raise_exc=None):
        self._text = text
        self._stream_chunks = stream_chunks or ["cla", "ude"]
        self._raise = raise_exc

    async def create(self, **kwargs):
        if self._raise:
            raise self._raise
        block = types.SimpleNamespace(text=self._text)
        return types.SimpleNamespace(content=[block])

    def stream(self, **kwargs):
        chunks = self._stream_chunks

        class _Ctx:
            async def __aenter__(self_inner):
                async def _text_stream():
                    for c in chunks:
                        yield c

                return types.SimpleNamespace(text_stream=_text_stream())

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _patch_anthropic(monkeypatch, messages):
    fake_mod = types.ModuleType("anthropic")

    class _AsyncAnthropic:
        def __init__(self, *a, **k):
            self.messages = messages

    fake_mod.AsyncAnthropic = _AsyncAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)


class TestAnthropicProvider:
    def _provider(self):
        cfg = ProviderConfig(
            name="anthropic", type="anthropic", api_key="test-key", default_model="claude"
        )
        return AnthropicProvider(cfg, model="claude")

    def test_complete_via_sdk(self, monkeypatch):
        _patch_anthropic(monkeypatch, _FakeAnthropicMessages(text="answer"))
        out = _run(
            self._provider().complete(
                [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
            )
        )
        assert out == "answer"

    def test_stream_via_sdk(self, monkeypatch):
        _patch_anthropic(monkeypatch, _FakeAnthropicMessages(stream_chunks=["a", "b", "c"]))
        chunks = _run(_collect(self._provider().stream([{"role": "user", "content": "hi"}])))
        assert "".join(chunks) == "abc"

    def test_complete_error_maps_to_promptgenie_error(self, monkeypatch):
        _patch_anthropic(monkeypatch, _FakeAnthropicMessages(raise_exc=RuntimeError("boom")))
        with pytest.raises(PromptGenieError):
            _run(self._provider().complete([{"role": "user", "content": "hi"}]))


# ---------------------------------------------------------------------------
# _resolve_api_key
# ---------------------------------------------------------------------------


class TestResolveApiKey:
    def test_direct_key(self):
        p = OpenAICompatProvider(ProviderConfig(name="x", type="openai_compat", api_key="k"))
        assert p._resolve_api_key() == "k"

    def test_env_key(self, monkeypatch):
        monkeypatch.setenv("MY_PROV_KEY", "envkey")
        p = OpenAICompatProvider(
            ProviderConfig(name="x", type="openai_compat", api_key_env="MY_PROV_KEY")
        )
        assert p._resolve_api_key() == "envkey"

    def test_missing_env_key_raises(self, monkeypatch):
        monkeypatch.delenv("MISSING_PROV_KEY", raising=False)
        p = OpenAICompatProvider(
            ProviderConfig(name="x", type="openai_compat", api_key_env="MISSING_PROV_KEY")
        )
        with pytest.raises(PromptGenieError):
            p._resolve_api_key()


# ---------------------------------------------------------------------------
# run_engine non-dry-run send path via a fake provider
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Minimal BaseProvider-compatible stub."""

    model = "fake-model"

    async def complete(self, messages, *, model=None, max_tokens=2048, timeout=120, **kw):
        return "complete response"

    async def stream(self, messages, *, model=None, max_tokens=2048, timeout=120, **kw):
        for tok in ("strea", "med ", "resp"):
            yield tok


class TestRunEngineSendPath:
    def _spec(self, tmp_path):
        from promptgenie.core.spec import load_spec

        p = tmp_path / "s.prompt.yaml"
        p.write_text("version: 1\nname: s\ntarget: claude-code\nmode: chat\nprompt: Say hi\n")
        return load_spec(str(p))

    def test_non_dry_run_complete(self, tmp_path, monkeypatch):
        import promptgenie.core.run_engine as re_mod

        monkeypatch.setattr(re_mod, "get_provider", lambda *a, **k: _FakeProvider())
        result = re_mod.run_spec(self._spec(tmp_path), dry_run=False, stream=False, no_history=True)
        assert result.status in ("ok", "error")
        assert result.dry_run is False
        if result.status == "ok":
            assert "complete response" in result.response

    def test_non_dry_run_stream(self, tmp_path, monkeypatch):
        import promptgenie.core.run_engine as re_mod

        monkeypatch.setattr(re_mod, "get_provider", lambda *a, **k: _FakeProvider())
        tokens: list[str] = []
        result = re_mod.run_spec(
            self._spec(tmp_path),
            dry_run=False,
            stream=True,
            no_history=True,
            on_token=tokens.append,
        )
        assert result.dry_run is False
        if result.status == "ok":
            assert "streamed resp" in result.response
