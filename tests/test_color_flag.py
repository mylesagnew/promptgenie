"""Regression tests: ``--color`` must reach every command's output.

``init_renderer()`` rebinds ``promptgenie.renderers.rich.console`` /
``diag_console`` once ``--color`` is resolved. Command modules that imported
those names by value (``from promptgenie.renderers.rich import console``) kept
the import-time objects, so ``--color never`` / ``--color always`` had no effect.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli

ANSI = "\x1b["
COMMANDS_DIR = Path(__file__).resolve().parent.parent / "promptgenie" / "commands"
MUTABLE = {"console", "diag_console"}
# Fixed separately in #146; drop from this set once that PR is merged.
PENDING = {"run.py", "make_cmd.py"}


def _lint_missing_config(*color_args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
    env["FORCE_COLOR"] = "1"  # import-time consoles come up coloured
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from promptgenie.cli import cli; cli()",
            *color_args,
            "lint",
            "missing.md",
            "--config",
            "/nonexistent/promptgenie.yaml",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_force_color_sanity_check() -> None:
    """Without ``--color``, FORCE_COLOR colours diagnostics (so the next test can fail)."""
    result = _lint_missing_config()
    assert "Config file not found" in result.stderr
    assert ANSI in result.stderr


def test_color_never_strips_ansi_from_diagnostics() -> None:
    result = _lint_missing_config("--color", "never")
    assert "Config file not found" in result.stderr
    assert ANSI not in result.stderr


def test_color_always_colours_diagnostics() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--color", "always", "lint", "missing.md", "--config", "/nonexistent/promptgenie.yaml"],
        env={"NO_COLOR": None, "FORCE_COLOR": None},
    )
    assert "Config file not found" in result.stderr
    assert ANSI in result.stderr


@pytest.mark.parametrize(
    "path",
    sorted(p for p in COMMANDS_DIR.glob("*.py") if p.name not in PENDING),
    ids=lambda p: p.name,
)
def test_commands_do_not_import_consoles_by_value(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "promptgenie.renderers.rich"
        for alias in node.names
        if alias.name in MUTABLE
    ]
    assert not bad, (
        f"{path.name} imports {bad} by value; use "
        "`from promptgenie.renderers import rich as renderer` and `renderer.console`"
    )
