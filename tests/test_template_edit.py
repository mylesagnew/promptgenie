"""Coverage for `promptgenie template edit` (editor stubbed, user layer sandboxed)."""

from __future__ import annotations

from click.testing import CliRunner

from promptgenie.cli import cli


class _FakeProc:
    returncode = 0


def _stub_editor(monkeypatch):
    import promptgenie.commands.template_cmd as tc

    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: _FakeProc())


def test_template_edit_not_found(monkeypatch):
    _stub_editor(monkeypatch)
    res = CliRunner().invoke(cli, ["template", "edit", "definitely-not-a-template-xyz"])
    assert res.exit_code != 0  # EXIT_USAGE for unknown template


def test_template_edit_builtin_copies_to_user_layer(monkeypatch, tmp_path):
    import promptgenie.core.template_store as ts

    # Redirect the user-template layer so the copy doesn't touch real config.
    monkeypatch.setattr(ts, "_USER_DIR", tmp_path / "user_templates")
    _stub_editor(monkeypatch)

    builtin = next(t for t in ts.list_all_templates() if t.source_layer == "builtin")
    res = CliRunner().invoke(cli, ["template", "edit", builtin.id])
    assert res.exit_code in (0, 1)
    # The built-in should have been copied into the sandboxed user layer.
    assert (tmp_path / "user_templates" / f"{builtin.id}.yaml").exists()
