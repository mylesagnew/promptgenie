"""Tests for promptgenie.core.run_engine — run pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from promptgenie.core.errors import PromptGenieError
from promptgenie.core.run_engine import (
    RunEvent,
    RunResult,
    _assemble_prompt,
    _build_messages,
    _git_is_clean,
    _infer_provider,
    run_spec,
)
from promptgenie.core.spec import ContextSource, OutputContract, PromptSpec, RunOptions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_spec(prompt: str = "Hello {{name}}", **kwargs) -> PromptSpec:
    return PromptSpec(
        version=1,
        name="test-run",
        target="claude-code",
        prompt=prompt,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# RunEvent
# ---------------------------------------------------------------------------


class TestRunEvent:
    def test_to_ndjson(self):
        evt = RunEvent("token", {"text": "hello"})
        line = evt.to_ndjson()
        import json
        obj = json.loads(line)
        assert obj["event"] == "token"
        assert obj["text"] == "hello"

    def test_done_event(self):
        evt = RunEvent("done", {"status": "ok"})
        line = evt.to_ndjson()
        import json
        obj = json.loads(line)
        assert obj["status"] == "ok"


# ---------------------------------------------------------------------------
# _infer_provider
# ---------------------------------------------------------------------------


class TestInferProvider:
    def test_claude_code_target(self):
        assert _infer_provider("claude-code") == "anthropic"

    def test_chatgpt_target(self):
        assert _infer_provider("chatgpt") == "openai"

    def test_unknown_defaults_to_anthropic(self):
        assert _infer_provider("unknown-xyz") == "anthropic"


# ---------------------------------------------------------------------------
# _assemble_prompt
# ---------------------------------------------------------------------------


class TestAssemblePrompt:
    def test_no_context(self):
        spec = _minimal_spec("Tell me about {{topic}}")
        result = _assemble_prompt(spec, {"topic": "Python"}, None)
        assert "Tell me about Python" in result

    def test_context_prepended(self):
        from promptgenie.core.context_builder import ContextManifest, SourceEntry
        spec = _minimal_spec("Answer the question.")
        manifest = ContextManifest(
            text="def foo(): pass",
            entries=[],
            total_tokens=5,
        )
        result = _assemble_prompt(spec, {}, manifest)
        assert "## Context" in result
        assert "def foo(): pass" in result
        assert "Answer the question." in result

    def test_empty_prompt(self):
        spec = _minimal_spec("")
        result = _assemble_prompt(spec, {}, None)
        assert result == ""


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------


class TestBuildMessages:
    def test_no_system_prompt(self):
        spec = _minimal_spec("Hello")
        messages = _build_messages(spec, "Hello")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_with_system_prompt(self):
        spec = _minimal_spec("Hello")
        spec.system_prompt = "You are a helper."
        messages = _build_messages(spec, "Hello")
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_empty_prompt_no_user_msg(self):
        spec = _minimal_spec("")
        messages = _build_messages(spec, "")
        # Empty prompt → no user message appended
        assert all(m["role"] != "user" or m["content"] != "" for m in messages)


# ---------------------------------------------------------------------------
# run_spec — dry run
# ---------------------------------------------------------------------------


class TestRunSpecDryRun:
    def test_dry_run_returns_dry_run_status(self, tmp_path):
        spec = _minimal_spec("Hello {{name}}")
        result = run_spec(spec, dry_run=True, cli_vars=["name=world"], no_input=True)
        assert result.dry_run is True
        assert result.status == "dry_run"
        assert result.response == ""

    def test_dry_run_resolves_vars(self, tmp_path):
        spec = _minimal_spec("Hello {{name}}")
        result = run_spec(spec, dry_run=True, cli_vars=["name=Alice"], no_input=True)
        assert result.resolved_vars.get("name") == "Alice"

    def test_dry_run_emits_done_event(self):
        spec = _minimal_spec("Hello")
        result = run_spec(spec, dry_run=True, no_input=True)
        done_events = [e for e in result.events if e.event == "done"]
        assert len(done_events) == 1
        assert done_events[0].data.get("status") == "dry_run"

    def test_dry_run_with_context(self, tmp_path):
        f = tmp_path / "ctx.txt"
        f.write_text("context content", encoding="utf-8")
        spec = _minimal_spec("Review this.")
        spec.context = [ContextSource(type="file", path=str(f))]
        spec._source_path = tmp_path / "spec.yaml"
        result = run_spec(spec, dry_run=True, no_input=True)
        assert result.context_manifest is not None
        assert "context content" in result.context_manifest.text

    def test_dry_run_require_clean_raises_if_dirty(self):
        spec = _minimal_spec("Hello")
        with patch("promptgenie.core.run_engine._git_is_clean", return_value=(False, "M file.py")):
            with pytest.raises(PromptGenieError) as exc_info:
                run_spec(spec, dry_run=True, require_clean=True, no_input=True)
            assert "dirty" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# run_spec — provider call (mocked)
# ---------------------------------------------------------------------------


class TestRunSpecWithProvider:
    def _mock_provider(self, response: str = "The answer is 42.") -> MagicMock:
        prov = MagicMock()
        prov.model = "claude-test"

        async def fake_complete(*a, **kw):
            return response

        async def fake_stream(*a, **kw):
            for chunk in response.split():
                yield chunk + " "

        prov.complete = fake_complete
        prov.stream = fake_stream
        return prov

    def test_non_streaming_complete(self):
        spec = _minimal_spec("What is the answer?")
        mock_prov = self._mock_provider("The answer is 42.")

        with patch("promptgenie.core.run_engine.get_provider", return_value=mock_prov):
            result = run_spec(spec, stream=False, no_input=True, no_history=True)

        assert result.status == "ok"
        assert "42" in result.response

    def test_streaming_collects_tokens(self):
        spec = _minimal_spec("What is the answer?")
        mock_prov = self._mock_provider("The answer is 42.")

        collected: list[str] = []

        with patch("promptgenie.core.run_engine.get_provider", return_value=mock_prov):
            result = run_spec(
                spec, stream=True, no_input=True, no_history=True,
                on_token=collected.append,
            )

        assert result.status == "ok"
        assert len(collected) > 0
        assert "".join(collected).strip() != ""

    def test_on_event_callback_called(self):
        spec = _minimal_spec("Question?")
        mock_prov = self._mock_provider("Answer.")
        events: list[RunEvent] = []

        with patch("promptgenie.core.run_engine.get_provider", return_value=mock_prov):
            run_spec(
                spec, stream=False, no_input=True, no_history=True,
                on_event=events.append,
            )

        event_types = {e.event for e in events}
        assert "start" in event_types
        assert "done" in event_types

    def test_tee_file_written(self, tmp_path):
        spec = _minimal_spec("Question?")
        mock_prov = self._mock_provider("The tee response.")
        tee = tmp_path / "tee.md"

        with patch("promptgenie.core.run_engine.get_provider", return_value=mock_prov):
            run_spec(
                spec, stream=False, no_input=True, no_history=True,
                tee_file=tee,
            )

        assert tee.exists()
        assert "tee response" in tee.read_text()

    def test_vars_resolved_before_prompt(self):
        spec = _minimal_spec("Deploy {{service}} to {{env}}")
        mock_prov = self._mock_provider("Done.")

        sent_messages: list = []

        async def fake_complete(messages, **kw):
            sent_messages.extend(messages)
            return "Done."

        mock_prov.complete = fake_complete

        with patch("promptgenie.core.run_engine.get_provider", return_value=mock_prov):
            run_spec(
                spec, stream=False, no_input=True, no_history=True,
                cli_vars=["service=api", "env=prod"],
            )

        user_msg = next(m for m in sent_messages if m["role"] == "user")
        assert "api" in user_msg["content"]
        assert "prod" in user_msg["content"]
