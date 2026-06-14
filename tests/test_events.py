"""Tests for the unified Event model, EventBus, and EventFormatters.

Covers:
  - EventKind enum values and _missing_ fallback
  - Event construction, serialisation (to_dict, to_ndjson), and property accessors
  - Event.from_run_event() legacy bridge
  - EventBus subscribe / subscribe_all / emit / emit_to / collected / of_kind / clear
  - NDJSONFormatter, TokenOnlyFormatter, SilentFormatter, RichFormatter
  - EventFormatter protocol structural check
  - run_engine integration: event_bus kwarg forwards RunEvents as Events
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from promptgenie.core.event_bus import EventBus
from promptgenie.core.event_formatters import (
    EventFormatter,
    NDJSONFormatter,
    RichFormatter,
    SilentFormatter,
    TokenOnlyFormatter,
)
from promptgenie.core.events import Event, EventKind


# ---------------------------------------------------------------------------
# EventKind
# ---------------------------------------------------------------------------


class TestEventKind:
    def test_all_run_kinds_present(self):
        expected = {
            "run.start", "run.token", "run.warning", "run.error",
            "run.tool_call", "run.done", "run.dry",
        }
        actual = {k.value for k in EventKind if k.value.startswith("run.")}
        assert expected <= actual

    def test_analysis_kinds(self):
        assert EventKind("lint.finding") == EventKind.LINT_FINDING
        assert EventKind("scan.finding") == EventKind.SCAN_FINDING

    def test_policy_kinds(self):
        assert EventKind("policy.pass") == EventKind.POLICY_PASS
        assert EventKind("policy.violation") == EventKind.POLICY_VIOLATION

    def test_other_domains(self):
        assert EventKind("diff.computed") == EventKind.DIFF_COMPUTED
        assert EventKind("eval.result") == EventKind.EVAL_RESULT
        assert EventKind("ci.check") == EventKind.CI_CHECK
        assert EventKind("audit.write") == EventKind.AUDIT_WRITE

    def test_missing_returns_unknown(self):
        result = EventKind("totally.unknown.kind")
        assert result == EventKind.UNKNOWN

    def test_string_equality(self):
        assert EventKind.RUN_TOKEN == "run.token"
        assert EventKind.RUN_DONE != "run.token"


# ---------------------------------------------------------------------------
# Event construction and serialisation
# ---------------------------------------------------------------------------


class TestEvent:
    def test_basic_construction(self):
        e = Event(EventKind.RUN_TOKEN, {"text": "hello"}, run_id="abc")
        assert e.kind == EventKind.RUN_TOKEN
        assert e.data == {"text": "hello"}
        assert e.run_id == "abc"
        assert e.ts > 0

    def test_default_run_id_is_generated(self):
        e1 = Event(EventKind.RUN_START)
        e2 = Event(EventKind.RUN_START)
        assert e1.run_id != e2.run_id

    def test_to_dict_flat(self):
        e = Event(EventKind.RUN_TOKEN, {"text": "hi"}, run_id="x1")
        d = e.to_dict()
        assert d["event"] == "run.token"
        assert d["run_id"] == "x1"
        assert d["text"] == "hi"
        assert "ts" in d

    def test_to_ndjson_is_valid_json(self):
        e = Event(EventKind.RUN_DONE, {"status": "ok"}, run_id="r1")
        line = e.to_ndjson()
        parsed = json.loads(line)
        assert parsed["event"] == "run.done"
        assert parsed["status"] == "ok"
        assert "\n" not in line

    def test_to_ndjson_no_trailing_newline(self):
        e = Event(EventKind.RUN_TOKEN, {"text": "x"})
        assert not e.to_ndjson().endswith("\n")

    def test_frozen_immutable(self):
        e = Event(EventKind.RUN_WARNING, {"message": "oops"})
        with pytest.raises((AttributeError, TypeError)):
            e.kind = EventKind.RUN_ERROR  # type: ignore[misc]

    def test_data_defaults_to_empty_dict(self):
        e = Event(EventKind.RUN_START)
        assert e.data == {}

    def test_text_property(self):
        e = Event(EventKind.RUN_TOKEN, {"text": "chunk"})
        assert e.text == "chunk"

    def test_text_property_missing(self):
        e = Event(EventKind.RUN_START)
        assert e.text == ""

    def test_message_property(self):
        e = Event(EventKind.RUN_WARNING, {"message": "be careful"})
        assert e.message == "be careful"

    def test_status_property(self):
        e = Event(EventKind.RUN_DONE, {"status": "ok"})
        assert e.status == "ok"

    def test_data_not_leaked_into_top_level_when_empty(self):
        e = Event(EventKind.RUN_START)
        d = e.to_dict()
        # Only event, run_id, ts at top level when data is empty
        assert set(d.keys()) == {"event", "run_id", "ts"}

    def test_multiple_data_fields_all_present(self):
        e = Event(EventKind.LINT_FINDING, {
            "code": "STRUCT_001", "severity": "MEDIUM", "line": 3
        })
        d = e.to_dict()
        assert d["code"] == "STRUCT_001"
        assert d["severity"] == "MEDIUM"
        assert d["line"] == 3


# ---------------------------------------------------------------------------
# Event.from_run_event() — legacy bridge
# ---------------------------------------------------------------------------


class TestFromRunEvent:
    def _make_run_event(self, kind: str, data: dict | None = None):
        """Build a minimal RunEvent-like object."""
        re = MagicMock()
        re.event = kind
        re.data = data or {}
        return re

    def test_start_maps_to_run_start(self):
        e = Event.from_run_event(self._make_run_event("start"))
        assert e.kind == EventKind.RUN_START

    def test_token_maps_to_run_token(self):
        e = Event.from_run_event(self._make_run_event("token", {"text": "x"}))
        assert e.kind == EventKind.RUN_TOKEN
        assert e.text == "x"

    def test_done_maps_to_run_done(self):
        e = Event.from_run_event(self._make_run_event("done", {"status": "ok"}))
        assert e.kind == EventKind.RUN_DONE
        assert e.status == "ok"

    def test_warning_maps(self):
        e = Event.from_run_event(self._make_run_event("warning", {"message": "m"}))
        assert e.kind == EventKind.RUN_WARNING

    def test_error_maps(self):
        e = Event.from_run_event(self._make_run_event("error"))
        assert e.kind == EventKind.RUN_ERROR

    def test_tool_call_maps(self):
        e = Event.from_run_event(self._make_run_event("tool_call", {"name": "bash"}))
        assert e.kind == EventKind.RUN_TOOL_CALL

    def test_unknown_legacy_kind_maps_to_unknown(self):
        e = Event.from_run_event(self._make_run_event("xyzzy"))
        assert e.kind == EventKind.UNKNOWN

    def test_run_id_passed_through(self):
        e = Event.from_run_event(self._make_run_event("start"), run_id="myrun")
        assert e.run_id == "myrun"

    def test_data_preserved(self):
        e = Event.from_run_event(
            self._make_run_event("done", {"status": "ok", "response_length": 42})
        )
        assert e.data["response_length"] == 42


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        seen: list[Event] = []
        bus.subscribe(EventKind.RUN_TOKEN, seen.append)
        bus.emit(Event(EventKind.RUN_TOKEN, {"text": "a"}))
        assert len(seen) == 1
        assert seen[0].text == "a"

    def test_subscribe_does_not_receive_other_kinds(self):
        bus = EventBus()
        seen: list[Event] = []
        bus.subscribe(EventKind.RUN_TOKEN, seen.append)
        bus.emit(Event(EventKind.RUN_DONE))
        assert seen == []

    def test_subscribe_all_receives_every_event(self):
        bus = EventBus()
        seen: list[Event] = []
        bus.subscribe_all(seen.append)
        bus.emit(Event(EventKind.RUN_START))
        bus.emit(Event(EventKind.RUN_TOKEN, {"text": "t"}))
        bus.emit(Event(EventKind.RUN_DONE))
        assert len(seen) == 3

    def test_multiple_subscribers_same_kind(self):
        bus = EventBus()
        a: list[Event] = []
        b: list[Event] = []
        bus.subscribe(EventKind.LINT_FINDING, a.append)
        bus.subscribe(EventKind.LINT_FINDING, b.append)
        bus.emit(Event(EventKind.LINT_FINDING))
        assert len(a) == 1
        assert len(b) == 1

    def test_collected_property(self):
        bus = EventBus()
        bus.emit(Event(EventKind.RUN_START))
        bus.emit(Event(EventKind.RUN_DONE))
        assert len(bus.collected) == 2

    def test_collected_returns_copy(self):
        bus = EventBus()
        bus.emit(Event(EventKind.RUN_START))
        c = bus.collected
        bus.emit(Event(EventKind.RUN_DONE))
        # Original snapshot not mutated
        assert len(c) == 1

    def test_of_kind_filters(self):
        bus = EventBus()
        bus.emit(Event(EventKind.RUN_TOKEN, {"text": "a"}))
        bus.emit(Event(EventKind.RUN_TOKEN, {"text": "b"}))
        bus.emit(Event(EventKind.RUN_DONE))
        tokens = bus.of_kind(EventKind.RUN_TOKEN)
        assert len(tokens) == 2
        assert all(t.kind == EventKind.RUN_TOKEN for t in tokens)

    def test_len(self):
        bus = EventBus()
        assert len(bus) == 0
        bus.emit(Event(EventKind.RUN_START))
        assert len(bus) == 1

    def test_clear_resets_everything(self):
        bus = EventBus()
        seen: list[Event] = []
        bus.subscribe(EventKind.RUN_TOKEN, seen.append)
        bus.emit(Event(EventKind.RUN_TOKEN))
        bus.clear()
        assert len(bus) == 0
        # Subscription also cleared — no callback after clear
        bus.emit(Event(EventKind.RUN_TOKEN))
        assert len(seen) == 1  # only the one before clear

    def test_emit_to_writes_to_stream(self):
        bus = EventBus()
        buf = io.StringIO()
        fmt = NDJSONFormatter()
        bus.emit_to(Event(EventKind.RUN_DONE, {"status": "ok"}), fmt, out=buf)
        written = buf.getvalue()
        assert written.endswith("\n")
        parsed = json.loads(written)
        assert parsed["event"] == "run.done"

    def test_emit_to_suppressed_when_formatter_returns_none(self):
        bus = EventBus()
        buf = io.StringIO()
        bus.emit_to(Event(EventKind.RUN_TOKEN), SilentFormatter(), out=buf)
        assert buf.getvalue() == ""

    def test_emit_to_still_dispatches_even_when_suppressed(self):
        bus = EventBus()
        seen: list[Event] = []
        bus.subscribe(EventKind.RUN_TOKEN, seen.append)
        buf = io.StringIO()
        bus.emit_to(Event(EventKind.RUN_TOKEN, {"text": "x"}), SilentFormatter(), out=buf)
        assert len(seen) == 1  # dispatched despite no output

    def test_repr(self):
        bus = EventBus()
        bus.emit(Event(EventKind.RUN_START))
        assert "1" in repr(bus)

    def test_catch_all_and_kind_subscriber_both_called(self):
        bus = EventBus()
        all_seen: list[Event] = []
        kind_seen: list[Event] = []
        bus.subscribe_all(all_seen.append)
        bus.subscribe(EventKind.RUN_DONE, kind_seen.append)
        bus.emit(Event(EventKind.RUN_DONE))
        assert len(all_seen) == 1
        assert len(kind_seen) == 1


# ---------------------------------------------------------------------------
# EventFormatter protocol structural check
# ---------------------------------------------------------------------------


class TestEventFormatterProtocol:
    def test_ndJSON_satisfies_protocol(self):
        assert isinstance(NDJSONFormatter(), EventFormatter)

    def test_token_only_satisfies_protocol(self):
        assert isinstance(TokenOnlyFormatter(), EventFormatter)

    def test_silent_satisfies_protocol(self):
        assert isinstance(SilentFormatter(), EventFormatter)

    def test_rich_satisfies_protocol(self):
        assert isinstance(RichFormatter(), EventFormatter)

    def test_custom_class_satisfies_protocol(self):
        class MyFmt:
            def format(self, event: Event) -> str | None:
                return "x"

        assert isinstance(MyFmt(), EventFormatter)


# ---------------------------------------------------------------------------
# NDJSONFormatter
# ---------------------------------------------------------------------------


class TestNDJSONFormatter:
    def setup_method(self):
        self.fmt = NDJSONFormatter()

    def test_emits_for_all_kinds(self):
        for kind in EventKind:
            result = self.fmt.format(Event(kind))
            assert result is not None

    def test_output_is_valid_json(self):
        result = self.fmt.format(Event(EventKind.RUN_TOKEN, {"text": "hi"}))
        parsed = json.loads(result)
        assert parsed["event"] == "run.token"

    def test_token_included(self):
        result = self.fmt.format(Event(EventKind.RUN_TOKEN, {"text": "chunk"}))
        assert "chunk" in result

    def test_run_done_status(self):
        result = self.fmt.format(Event(EventKind.RUN_DONE, {"status": "ok"}))
        parsed = json.loads(result)
        assert parsed["status"] == "ok"


# ---------------------------------------------------------------------------
# TokenOnlyFormatter
# ---------------------------------------------------------------------------


class TestTokenOnlyFormatter:
    def setup_method(self):
        self.fmt = TokenOnlyFormatter()

    def test_emits_token_text(self):
        result = self.fmt.format(Event(EventKind.RUN_TOKEN, {"text": "hello"}))
        assert result == "hello"

    def test_suppresses_non_token_events(self):
        for kind in [
            EventKind.RUN_START, EventKind.RUN_DONE, EventKind.RUN_WARNING,
            EventKind.LINT_FINDING, EventKind.SCAN_FINDING, EventKind.POLICY_VIOLATION,
        ]:
            assert self.fmt.format(Event(kind)) is None

    def test_empty_text_produces_empty_string(self):
        result = self.fmt.format(Event(EventKind.RUN_TOKEN, {}))
        assert result == ""


# ---------------------------------------------------------------------------
# SilentFormatter
# ---------------------------------------------------------------------------


class TestSilentFormatter:
    def test_suppresses_everything(self):
        fmt = SilentFormatter()
        for kind in EventKind:
            assert fmt.format(Event(kind)) is None


# ---------------------------------------------------------------------------
# RichFormatter
# ---------------------------------------------------------------------------


class TestRichFormatter:
    def setup_method(self):
        self.fmt = RichFormatter()

    def test_suppresses_token_events(self):
        assert self.fmt.format(Event(EventKind.RUN_TOKEN, {"text": "x"})) is None

    def test_emits_for_run_warning(self):
        result = self.fmt.format(Event(EventKind.RUN_WARNING, {"message": "low tokens"}))
        assert result is not None
        assert "low tokens" in result
        assert "warning" in result.lower() or "⚠" in result

    def test_emits_for_run_error(self):
        result = self.fmt.format(Event(EventKind.RUN_ERROR, {"message": "timeout"}))
        assert result is not None
        assert "timeout" in result

    def test_emits_for_run_start(self):
        result = self.fmt.format(Event(EventKind.RUN_START, {"spec_name": "my-spec"}))
        assert result is not None
        assert "run.start" in result

    def test_emits_for_run_done(self):
        result = self.fmt.format(Event(EventKind.RUN_DONE, {"status": "ok"}))
        assert result is not None
        assert "run.done" in result

    def test_lint_finding_includes_code_and_severity(self):
        result = self.fmt.format(Event(EventKind.LINT_FINDING, {
            "code": "STRUCT_001", "severity": "MEDIUM", "message": "no scope"
        }))
        assert result is not None
        assert "STRUCT_001" in result
        assert "MEDIUM" in result

    def test_scan_finding_includes_code_and_risk(self):
        result = self.fmt.format(Event(EventKind.SCAN_FINDING, {
            "code": "SEC_001", "risk": "HIGH", "message": "injection"
        }))
        assert result is not None
        assert "SEC_001" in result
        assert "HIGH" in result

    def test_policy_violation_includes_rule_and_message(self):
        result = self.fmt.format(Event(EventKind.POLICY_VIOLATION, {
            "rule": "max_risk", "message": "1 finding at or above HIGH"
        }))
        assert result is not None
        assert "max_risk" in result

    def test_policy_pass(self):
        result = self.fmt.format(Event(EventKind.POLICY_PASS))
        assert result is not None
        assert "passed" in result.lower()

    def test_tool_call_includes_name(self):
        result = self.fmt.format(Event(EventKind.RUN_TOOL_CALL, {"name": "bash_exec"}))
        assert result is not None
        assert "bash_exec" in result

    def test_eval_result_includes_model_and_score(self):
        result = self.fmt.format(Event(EventKind.EVAL_RESULT, {
            "model": "gpt-4", "score": 87
        }))
        assert result is not None
        assert "gpt-4" in result
        assert "87" in result

    def test_ci_check_pass(self):
        result = self.fmt.format(Event(EventKind.CI_CHECK, {"check": "lint", "passed": True}))
        assert result is not None
        assert "lint" in result

    def test_ci_check_fail(self):
        result = self.fmt.format(Event(EventKind.CI_CHECK, {"check": "scan", "passed": False}))
        assert result is not None

    def test_audit_write_includes_row_id(self):
        result = self.fmt.format(Event(EventKind.AUDIT_WRITE, {"row_id": 42}))
        assert result is not None
        assert "42" in result

    def test_diff_computed(self):
        result = self.fmt.format(Event(EventKind.DIFF_COMPUTED, {"section_count": 5}))
        assert result is not None
        assert "5" in result

    def test_unknown_kind_produces_output(self):
        result = self.fmt.format(Event(EventKind.UNKNOWN))
        assert result is not None


# ---------------------------------------------------------------------------
# run_engine integration — event_bus kwarg
# ---------------------------------------------------------------------------


class TestRunEngineEventBusIntegration:
    def test_event_bus_receives_run_events(self):
        """run_spec with event_bus= should forward RunEvents to the bus."""
        from promptgenie.core.event_bus import EventBus
        from promptgenie.core.events import EventKind

        bus = EventBus()

        # We don't need a real provider — just verify the forwarding
        # by checking that a bus is accepted without error and that
        # events are forwarded from a dry-run (which doesn't need a provider).
        from promptgenie.core.spec import PromptSpec
        spec = PromptSpec(
            version=1,
            name="test-bus",
            target="claude-code",
            prompt="Hello",
        )

        with patch("promptgenie.core.run_engine._git_is_clean", return_value=(True, "")):
            from promptgenie.core.run_engine import run_spec
            result = run_spec(spec, dry_run=True, event_bus=bus)

        assert result.status == "dry_run"
        # At minimum the dry-run "done" event should have been forwarded
        done_events = bus.of_kind(EventKind.RUN_DONE)
        assert len(done_events) >= 1

    def test_bus_error_does_not_break_run(self):
        """A broken bus subscriber must not propagate into the run pipeline."""
        from promptgenie.core.event_bus import EventBus
        from promptgenie.core.spec import PromptSpec

        bus = EventBus()
        bus.subscribe_all(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))

        spec = PromptSpec(version=1, name="bus-error-test", target="claude-code", prompt="Hi")

        with patch("promptgenie.core.run_engine._git_is_clean", return_value=(True, "")):
            from promptgenie.core.run_engine import run_spec
            # Should not raise
            result = run_spec(spec, dry_run=True, event_bus=bus)

        assert result.status == "dry_run"
