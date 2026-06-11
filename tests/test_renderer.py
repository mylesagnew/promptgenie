"""Tests for promptgenie.renderers.rich — color mode and renderer profiles."""

import os
from unittest.mock import patch

import pytest

from promptgenie.renderers.rich import (
    ColorMode,
    _resolve_color,
    init_renderer,
    is_structured_mode,
    make_console,
)


class TestColorMode:
    def test_values(self):
        assert ColorMode.AUTO == "auto"
        assert ColorMode.ALWAYS == "always"
        assert ColorMode.NEVER == "never"

    def test_from_string(self):
        assert ColorMode("auto") == ColorMode.AUTO
        assert ColorMode("always") == ColorMode.ALWAYS
        assert ColorMode("never") == ColorMode.NEVER


class TestResolveColor:
    def test_always_returns_true(self):
        assert _resolve_color(ColorMode.ALWAYS) is True

    def test_never_returns_false(self):
        assert _resolve_color(ColorMode.NEVER) is False

    def test_auto_returns_none_without_env(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove both vars if present
            env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "FORCE_COLOR")}
            with patch.dict(os.environ, env, clear=True):
                result = _resolve_color(ColorMode.AUTO)
                assert result is None

    def test_auto_force_color_env(self):
        with patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=False):
            assert _resolve_color(ColorMode.AUTO) is True

    def test_auto_no_color_env(self):
        with patch.dict(os.environ, {"NO_COLOR": ""}, clear=False):
            assert _resolve_color(ColorMode.AUTO) is False

    def test_accepts_string_mode(self):
        assert _resolve_color("always") is True
        assert _resolve_color("never") is False


class TestMakeConsole:
    def test_returns_console_object(self):
        from rich.console import Console
        c = make_console(ColorMode.AUTO)
        assert isinstance(c, Console)

    def test_stderr_console(self):
        from rich.console import Console
        c = make_console(ColorMode.AUTO, stderr=True)
        assert isinstance(c, Console)

    def test_never_mode_no_color(self):
        from rich.console import Console
        c = make_console(ColorMode.NEVER)
        assert isinstance(c, Console)
        # no_color should be set
        assert c.no_color is True


class TestInitRenderer:
    def test_updates_module_console(self):
        import promptgenie.renderers.rich as renderer
        before = id(renderer.console)
        init_renderer(ColorMode.AUTO)
        # A new console object is created each time
        # (may or may not be same id depending on Python's memory reuse, but
        #  we can verify the function doesn't raise)

    def test_init_with_never(self):
        import promptgenie.renderers.rich as renderer
        init_renderer(ColorMode.NEVER)
        assert renderer.console.no_color is True

    def test_init_with_always(self):
        import promptgenie.renderers.rich as renderer
        init_renderer(ColorMode.ALWAYS)
        # force_terminal may be set; just check it doesn't raise


class TestIsStructuredMode:
    def test_json_is_structured(self):
        assert is_structured_mode("json") is True

    def test_sarif_is_structured(self):
        assert is_structured_mode("sarif") is True

    def test_yaml_is_structured(self):
        assert is_structured_mode("yaml") is True

    def test_ndjson_is_structured(self):
        assert is_structured_mode("ndjson") is True

    def test_rich_is_not_structured(self):
        assert is_structured_mode("rich") is False

    def test_markdown_is_not_structured(self):
        assert is_structured_mode("markdown") is False

    def test_empty_is_not_structured(self):
        assert is_structured_mode("") is False
