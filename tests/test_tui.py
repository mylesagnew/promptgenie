"""Textual TUI coverage (roadmap #2). Requires the [tui] extra; skipped otherwise.

Drives the app headlessly via Textual's ``App.run_test()`` pilot.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from promptgenie.commands.tui_cmd import build_tui_app  # noqa: E402

_PROMPT = "## Objective\nReview the auth module.\n\n## Output Format\nUnified diff.\n"


def _run(coro):
    return asyncio.run(coro)


def test_loads_file_and_status(tmp_path):
    f = tmp_path / "p.md"
    f.write_text(_PROMPT)
    app = build_tui_app(file=str(f), provider="claude", model="opus")

    async def _drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            from textual.widgets import Static, TextArea

            assert app.query_one("#editor", TextArea).text == _PROMPT
            status = app.query_one("#status-bar", Static)
            assert status is not None

    _run(_drive())


def test_lint_action_updates_score_and_panel(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("help me fix the whole app and deploy to production\n")
    app = build_tui_app(file=str(f))

    async def _drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_lint_prompt()
            await pilot.pause()
            # score is a reactive int that lint sets
            assert isinstance(app.score, int)

    _run(_drive())


def test_save_then_diff(tmp_path):
    f = tmp_path / "p.md"
    f.write_text(_PROMPT)
    app = build_tui_app(file=str(f), read_only=False)

    async def _drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            from textual.widgets import TextArea

            editor = app.query_one("#editor", TextArea)
            editor.load_text(_PROMPT + "\nextra line\n")
            app.action_save()
            await pilot.pause()
            app.action_diff_prompt()  # current == last_saved now → "no changes" path
            editor.load_text(_PROMPT + "\nmore\n")
            app.action_diff_prompt()  # changed → diff path
            await pilot.pause()

    _run(_drive())
    assert "extra line" in f.read_text()  # save persisted


def test_read_only_save_is_noop(tmp_path):
    f = tmp_path / "p.md"
    f.write_text(_PROMPT)
    app = build_tui_app(file=str(f), read_only=True)

    async def _drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            from textual.widgets import TextArea

            app.query_one("#editor", TextArea).load_text("changed in read-only")
            app.action_save()
            await pilot.pause()

    _run(_drive())
    assert f.read_text() == _PROMPT  # unchanged


def test_run_and_test_actions(tmp_path):
    f = tmp_path / "p.md"
    f.write_text(_PROMPT)
    # adjacent eval suite to exercise the Ctrl+T path
    (tmp_path / "p.eval.yaml").write_text(
        "name: s\nprompt: p.md\ncases:\n  - name: c\n    assert:\n      - type: contains\n        value: diff\n"
    )
    app = build_tui_app(file=str(f), provider=None)

    async def _drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_run_prompt()  # no provider → warning path
            app.action_test_prompt()  # adjacent eval suite path
            await pilot.pause()

    _run(_drive())


def test_keybindings_via_pilot(tmp_path):
    f = tmp_path / "p.md"
    f.write_text(_PROMPT)
    app = build_tui_app(file=str(f))

    async def _drive():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+l")  # lint binding
            await pilot.pause()

    _run(_drive())
