"""Integration tests for the provider → HTTP → parse → metric pipeline.

Each test replays a pre-recorded Anthropic API response from tests/cassettes/
using respx (an httpx interceptor), so no real API credentials are needed and
these tests are safe to run in CI.

To re-record cassettes against the real API:
    ANTHROPIC_API_KEY=<key> pytest -m integration --respx-passthrough

The ``@pytest.mark.integration`` marker exists so you can run this suite in
isolation:
    pytest -m integration
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from promptgenie.core.providers import AnthropicProvider, ProviderConfig

CASSETTES = Path(__file__).parent / "cassettes"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _load_cassette(name: str) -> dict:
    return json.loads((CASSETTES / name).read_text())


def _make_anthropic_provider(model: str = "claude-haiku-4-5") -> AnthropicProvider:
    """Build an AnthropicProvider with a fake API key (no env var needed)."""
    cfg = ProviderConfig(
        name="test-anthropic",
        type="anthropic",
        api_key="sk-test-cassette-key",
        default_model=model,
    )
    return AnthropicProvider(cfg, model=model)


# ---------------------------------------------------------------------------
# Direct httpx-path tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAnthropicHttpxCassette:
    """AnthropicProvider._complete_httpx() replays a cassette via respx."""

    def test_complete_returns_cassette_text(self):
        data = _load_cassette("anthropic_haiku.json")
        expected = data["content"][0]["text"]

        with respx.mock() as mock:
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            provider = _make_anthropic_provider()
            result = asyncio.run(
                provider._complete_httpx(
                    [{"role": "user", "content": "Say hello."}],
                    None,
                    "claude-haiku-4-5",
                    64,
                    5,
                )
            )

        assert result == expected

    def test_complete_sends_correct_request_body(self):
        data = _load_cassette("anthropic_haiku.json")
        captured: list[dict] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=data)

        with respx.mock() as mock:
            mock.post(_ANTHROPIC_URL).mock(side_effect=_handler)
            provider = _make_anthropic_provider()
            asyncio.run(
                provider._complete_httpx(
                    [{"role": "user", "content": "Hello."}],
                    "You are helpful.",
                    "claude-haiku-4-5",
                    128,
                    5,
                )
            )

        assert len(captured) == 1
        body = captured[0]
        assert body["model"] == "claude-haiku-4-5"
        assert body["max_tokens"] == 128
        assert body["system"] == "You are helpful."
        assert body["messages"][0] == {"role": "user", "content": "Hello."}

    def test_complete_without_system_omits_system_key(self):
        data = _load_cassette("anthropic_haiku.json")
        captured: list[dict] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=data)

        with respx.mock() as mock:
            mock.post(_ANTHROPIC_URL).mock(side_effect=_handler)
            provider = _make_anthropic_provider()
            asyncio.run(
                provider._complete_httpx(
                    [{"role": "user", "content": "Hi."}],
                    None,  # no system
                    "claude-haiku-4-5",
                    64,
                    5,
                )
            )

        assert "system" not in captured[0]

    def test_complete_propagates_http_error(self):
        with respx.mock() as mock:
            mock.post(_ANTHROPIC_URL).mock(
                return_value=httpx.Response(429, json={"error": {"type": "rate_limit_error"}})
            )
            provider = _make_anthropic_provider()
            with pytest.raises(Exception):
                asyncio.run(
                    provider._complete_httpx(
                        [{"role": "user", "content": "Hi."}],
                        None,
                        "claude-haiku-4-5",
                        64,
                        5,
                    )
                )


# ---------------------------------------------------------------------------
# Full stack: complete() → _complete_httpx (anthropic import forced absent)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAnthropicCompleteCassette:
    """AnthropicProvider.complete() selects the httpx fallback when the SDK is absent."""

    def test_complete_via_httpx_fallback(self):
        data = _load_cassette("anthropic_haiku.json")
        expected = data["content"][0]["text"]

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            provider = _make_anthropic_provider()
            result = asyncio.run(
                provider.complete(
                    [{"role": "user", "content": "Say hello."}],
                    model="claude-haiku-4-5",
                    max_tokens=64,
                    timeout=5,
                )
            )

        assert result == expected


# ---------------------------------------------------------------------------
# run_eval_suite end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEvalSuiteCassette:
    """run_eval_suite() with a cassette-backed provider, testing assertion types."""

    def _patched_get_provider(self, provider: AnthropicProvider):
        """Return a monkeypatch-friendly get_provider replacement."""
        return lambda name, model_override=None: provider

    def test_contains_assertion_passes(self, monkeypatch):
        from promptgenie.core import providers as prov_mod
        from promptgenie.core.eval_suite import EvalAssertion, EvalCase, EvalSuite, run_eval_suite

        data = _load_cassette("anthropic_haiku.json")
        response_text = data["content"][0]["text"]
        provider = _make_anthropic_provider()
        monkeypatch.setattr(prov_mod, "get_provider", self._patched_get_provider(provider))

        suite = EvalSuite(
            name="cassette-suite",
            provider="test-anthropic",
            model="claude-haiku-4-5",
            cases=[
                EvalCase(
                    name="greeting-check",
                    input="Write a greeting.",
                    assertions=[EvalAssertion(type="contains", value=response_text[:15])],
                )
            ],
        )

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            result = run_eval_suite(suite, timeout=5)

        assert result.passed
        assert result.pass_count == 1
        assert result.cases[0].response == response_text

    def test_not_contains_assertion_passes(self, monkeypatch):
        from promptgenie.core import providers as prov_mod
        from promptgenie.core.eval_suite import EvalAssertion, EvalCase, EvalSuite, run_eval_suite

        data = _load_cassette("anthropic_haiku.json")
        provider = _make_anthropic_provider()
        monkeypatch.setattr(prov_mod, "get_provider", self._patched_get_provider(provider))

        suite = EvalSuite(
            name="cassette-suite",
            provider="test-anthropic",
            model="claude-haiku-4-5",
            cases=[
                EvalCase(
                    name="no-jailbreak",
                    input="Write a greeting.",
                    assertions=[
                        EvalAssertion(type="not_contains", value="XYZZY_IMPOSSIBLE_TOKEN_99999")
                    ],
                )
            ],
        )

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            result = run_eval_suite(suite, timeout=5)

        assert result.passed

    def test_max_tokens_assertion_short_response_passes(self, monkeypatch):
        from promptgenie.core import providers as prov_mod
        from promptgenie.core.eval_suite import EvalAssertion, EvalCase, EvalSuite, run_eval_suite

        data = _load_cassette("anthropic_haiku.json")
        provider = _make_anthropic_provider()
        monkeypatch.setattr(prov_mod, "get_provider", self._patched_get_provider(provider))

        suite = EvalSuite(
            name="cassette-suite",
            provider="test-anthropic",
            model="claude-haiku-4-5",
            cases=[
                EvalCase(
                    name="brevity-check",
                    input="Write a greeting.",
                    assertions=[EvalAssertion(type="max_tokens", value=500)],
                )
            ],
        )

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            result = run_eval_suite(suite, timeout=5)

        assert result.passed

    def test_contains_assertion_fails_when_text_absent(self, monkeypatch):
        from promptgenie.core import providers as prov_mod
        from promptgenie.core.eval_suite import EvalAssertion, EvalCase, EvalSuite, run_eval_suite

        data = _load_cassette("anthropic_haiku.json")
        provider = _make_anthropic_provider()
        monkeypatch.setattr(prov_mod, "get_provider", self._patched_get_provider(provider))

        suite = EvalSuite(
            name="cassette-suite",
            provider="test-anthropic",
            model="claude-haiku-4-5",
            cases=[
                EvalCase(
                    name="wrong-contains",
                    input="Write a greeting.",
                    assertions=[
                        EvalAssertion(type="contains", value="XYZZY_IMPOSSIBLE_TOKEN_99999")
                    ],
                )
            ],
        )

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            result = run_eval_suite(suite, timeout=5)

        assert not result.passed
        assert result.fail_count == 1

    def test_suite_result_has_latency(self, monkeypatch):
        from promptgenie.core import providers as prov_mod
        from promptgenie.core.eval_suite import EvalCase, EvalSuite, run_eval_suite

        data = _load_cassette("anthropic_haiku.json")
        provider = _make_anthropic_provider()
        monkeypatch.setattr(prov_mod, "get_provider", self._patched_get_provider(provider))

        suite = EvalSuite(
            name="cassette-suite",
            provider="test-anthropic",
            model="claude-haiku-4-5",
            cases=[EvalCase(name="latency-check", input="Hi.")],
        )

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            result = run_eval_suite(suite, timeout=5)

        assert result.cases[0].latency_ms >= 0


# ---------------------------------------------------------------------------
# matrix_evaluate end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMatrixEvaluateCassette:
    """matrix_evaluate() with a cassette-backed provider."""

    def test_single_model_returns_response(self, monkeypatch):
        from promptgenie.core import providers as prov_mod
        from promptgenie.core.evaluator import matrix_evaluate

        data = _load_cassette("anthropic_haiku.json")
        expected = data["content"][0]["text"]
        provider = _make_anthropic_provider()
        monkeypatch.setattr(prov_mod, "get_provider", lambda name, model_override=None: provider)

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            result = matrix_evaluate(
                "Say hello.",
                models=["anthropic/claude-haiku-4-5"],
                timeout=5,
            )

        assert len(result.results) == 1
        r = result.results[0]
        assert r.response == expected
        assert r.error is None
        assert r.metrics.latency_ms >= 0

    def test_metrics_include_token_counts(self, monkeypatch):
        from promptgenie.core import providers as prov_mod
        from promptgenie.core.evaluator import matrix_evaluate

        data = _load_cassette("anthropic_haiku.json")
        provider = _make_anthropic_provider()
        monkeypatch.setattr(prov_mod, "get_provider", lambda name, model_override=None: provider)

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            result = matrix_evaluate("Say hello.", models=["anthropic/claude-haiku-4-5"], timeout=5)

        metrics = result.results[0].metrics
        assert metrics.total_tokens > 0
        assert metrics.input_tokens > 0
        assert metrics.output_tokens > 0

    def test_prompt_preserved_in_result(self, monkeypatch):
        from promptgenie.core import providers as prov_mod
        from promptgenie.core.evaluator import matrix_evaluate

        data = _load_cassette("anthropic_haiku.json")
        provider = _make_anthropic_provider()
        monkeypatch.setattr(prov_mod, "get_provider", lambda name, model_override=None: provider)

        with (
            patch.dict(sys.modules, {"anthropic": None}),
            respx.mock() as mock,
        ):
            mock.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=data))
            result = matrix_evaluate("What is 2+2?", models=["anthropic/claude-haiku-4-5"], timeout=5)

        assert result.prompt == "What is 2+2?"
