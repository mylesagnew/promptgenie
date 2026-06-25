"""Regression: context packs with None/blank list entries must not crash.

A scaffolded pack (`pack init`) seeds list fields with `- # comment` placeholder
lines that YAML parses as None. Previously `pack list` did `", ".join(stack)`
and raised TypeError on the None items.
"""

from __future__ import annotations

from click.testing import CliRunner

import promptgenie.core.context_packs as cp
from promptgenie.cli import cli

_PACK_WITH_NONES = """\
name: bad
description: ""
stack:
  - # placeholder comment -> None
  - React 18
architecture:
  - # placeholder -> None
coding_style:
  -
known_pitfalls:
  - Watch out
  -
"""


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "PACKS_DIR", tmp_path)
    (tmp_path / "bad.yaml").write_text(_PACK_WITH_NONES, encoding="utf-8")


def test_list_packs_drops_none_entries(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    packs = cp.list_packs()
    bad = next(p for p in packs if p["id"] == "bad")
    assert bad["stack"] == ["React 18"]  # None entry dropped
    assert isinstance(bad["name"], str) and isinstance(bad["description"], str)


def test_load_pack_normalises_list_fields(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    data = cp.load_pack("bad")
    assert data["stack"] == ["React 18"]
    assert data["architecture"] == []
    assert data["coding_style"] == []
    assert data["known_pitfalls"] == ["Watch out"]


def test_render_pack_has_no_none_lines(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    rendered = cp.render_pack("bad", mode="exhaustive")
    assert "None" not in rendered
    assert "React 18" in rendered


def test_pack_list_command_does_not_crash(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["pack", "list"])
    assert result.exit_code == 0, result.output
    assert "bad" in result.output


def test_pack_show_command_on_sparse_pack(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["pack", "show", "bad"])
    assert result.exit_code == 0, result.output
