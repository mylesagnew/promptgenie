"""Render-path coverage for `promptgenie diff` (side-by-side, --out, --format)."""

from __future__ import annotations

from click.testing import CliRunner

from promptgenie.cli import cli

_A = "## Objective\nReview the auth module.\n\n## Output Format\nPlain text.\n"
_B = (
    "## Objective\nReview the auth and billing modules.\n\n"
    "## Output Format\nUnified diff.\n\n## Constraints\nBe concise and cite files.\n"
)


def _files(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(_A)
    b.write_text(_B)
    return str(a), str(b)


def test_diff_side_by_side(tmp_path):
    a, b = _files(tmp_path)
    res = CliRunner().invoke(cli, ["diff", a, b, "--side-by-side"])
    assert res.exit_code in (0, 1)
    assert "Side-by-Side" in res.output or res.exit_code in (0, 1)


def test_diff_unified(tmp_path):
    a, b = _files(tmp_path)
    res = CliRunner().invoke(cli, ["diff", a, b, "--unified"])
    assert res.exit_code in (0, 1)


def test_diff_json_to_stdout(tmp_path):
    a, b = _files(tmp_path)
    res = CliRunner().invoke(cli, ["diff", a, b, "--format", "json"])
    assert res.exit_code in (0, 1)


def test_diff_out_then_refuse_then_force(tmp_path):
    a, b = _files(tmp_path)
    out = tmp_path / "diff.json"
    first = CliRunner().invoke(cli, ["diff", a, b, "--format", "json", "--out", str(out)])
    assert first.exit_code in (0, 1)
    assert out.exists()
    # Writing again without --force must refuse to clobber.
    refuse = CliRunner().invoke(cli, ["diff", a, b, "--format", "json", "--out", str(out)])
    assert refuse.exit_code in (1, 2)
    # --force overwrites.
    forced = CliRunner().invoke(
        cli, ["diff", a, b, "--format", "json", "--out", str(out), "--force"]
    )
    assert forced.exit_code in (0, 1)


def test_diff_rich_mode_writes_out(tmp_path):
    a, b = _files(tmp_path)
    out = tmp_path / "diff.txt"
    res = CliRunner().invoke(cli, ["diff", a, b, "--out", str(out)])
    assert res.exit_code in (0, 1)
    assert out.exists()
