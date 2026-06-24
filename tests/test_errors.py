"""Tests for promptgenie.core.errors — exit codes and PromptGenieError."""

import pytest

from promptgenie.core.errors import (
    EXIT_FAILURE,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_PROVIDER,
    EXIT_SECRETS,
    EXIT_TEMPLATE,
    EXIT_TEST,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    PromptGenieError,
    _code_label,
    handle_error,
)


class TestExitCodeValues:
    def test_ok_is_zero(self):
        assert EXIT_OK == 0

    def test_failure_is_one(self):
        assert EXIT_FAILURE == 1

    def test_usage_is_two(self):
        assert EXIT_USAGE == 2

    def test_provider_is_three(self):
        assert EXIT_PROVIDER == 3

    def test_template_is_four(self):
        assert EXIT_TEMPLATE == 4

    def test_test_is_five(self):
        assert EXIT_TEST == 5

    def test_secrets_is_six(self):
        assert EXIT_SECRETS == 6

    def test_timeout_is_seven(self):
        assert EXIT_TIMEOUT == 7

    def test_interrupted_is_130(self):
        assert EXIT_INTERRUPTED == 130

    def test_all_codes_are_distinct(self):
        codes = [
            EXIT_OK,
            EXIT_FAILURE,
            EXIT_USAGE,
            EXIT_PROVIDER,
            EXIT_TEMPLATE,
            EXIT_TEST,
            EXIT_SECRETS,
            EXIT_TIMEOUT,
            EXIT_INTERRUPTED,
        ]
        assert len(codes) == len(set(codes))


class TestPromptGenieError:
    def test_default_code_is_usage(self):
        exc = PromptGenieError("something went wrong")
        assert exc.code == EXIT_USAGE

    def test_custom_code(self):
        exc = PromptGenieError("network down", code=EXIT_PROVIDER)
        assert exc.code == EXIT_PROVIDER

    def test_message_preserved(self):
        exc = PromptGenieError("bad template", code=EXIT_TEMPLATE)
        assert str(exc) == "bad template"

    def test_hint_field(self):
        exc = PromptGenieError("oops", hint="Try --best-effort")
        assert exc.hint == "Try --best-effort"

    def test_no_hint_by_default(self):
        exc = PromptGenieError("oops")
        assert exc.hint == ""

    def test_is_exception_subclass(self):
        exc = PromptGenieError("x")
        assert isinstance(exc, Exception)


class TestCodeLabel:
    def test_known_codes(self):
        assert "Error" in _code_label(EXIT_USAGE)
        assert "Failure" in _code_label(EXIT_FAILURE)
        assert "Provider" in _code_label(EXIT_PROVIDER)
        assert "Template" in _code_label(EXIT_TEMPLATE)
        assert "Test" in _code_label(EXIT_TEST)

    def test_unknown_code_returns_error(self):
        assert _code_label(99) == "Error"


class TestHandleError:
    def test_raises_system_exit_with_code(self):
        exc = PromptGenieError("boom", code=EXIT_TEMPLATE)
        with pytest.raises(SystemExit) as exc_info:
            handle_error(exc, use_stderr=True)
        assert exc_info.value.code == EXIT_TEMPLATE

    def test_hint_included_when_set(self, capsys):
        exc = PromptGenieError("bad arg", hint="Use --help", code=EXIT_USAGE)
        with pytest.raises(SystemExit):
            handle_error(exc, use_stderr=False)
        captured = capsys.readouterr()
        assert "Use --help" in captured.out
