"""Tests for ReDoS protection in prompt-test regex handling (Wave 2.3)."""

import pytest

from promptgenie.core.tester import _MAX_REGEX_LEN, _safe_search


class TestSafeSearch:
    def test_simple_match(self):
        matched, err = _safe_search(r"hello", "say hello world")
        assert matched is True
        assert err is None

    def test_simple_no_match(self):
        matched, err = _safe_search(r"goodbye", "say hello world")
        assert matched is False
        assert err is None

    def test_case_insensitive(self):
        matched, err = _safe_search(r"HELLO", "say hello world")
        assert matched is True
        assert err is None

    def test_invalid_regex_returns_error(self):
        matched, err = _safe_search(r"[unclosed", "some text")
        assert matched is False
        assert err is not None
        assert "invalid regex" in err

    def test_regex_too_long_rejected(self):
        long_pattern = "a" * (_MAX_REGEX_LEN + 1)
        matched, err = _safe_search(long_pattern, "aaaa")
        assert matched is False
        assert err is not None
        assert "too long" in err

    def test_exactly_max_length_accepted(self):
        pattern = "a" * _MAX_REGEX_LEN
        matched, err = _safe_search(pattern, "a" * _MAX_REGEX_LEN)
        assert err is None

    def test_known_redos_pattern_handled(self):
        # (a+)+ against a long non-matching string is a classic ReDoS trigger.
        # On POSIX with SIGALRM this should timeout; on other platforms it may
        # complete quickly or not — we just assert it doesn't hang the suite.
        import sys

        if sys.platform == "win32":
            pytest.skip("SIGALRM not available on Windows")
        pattern = r"(a+)+"
        text = "a" * 25 + "b"
        # This call must return — timeout or result, but not hang.
        matched, err = _safe_search(pattern, text)
        # Either timed out (err set) or matched/didn't-match (no error)
        assert isinstance(matched, bool)
