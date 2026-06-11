"""completion.py — shell completion installer for PromptGenie.

Supports zsh, bash, and fish.  Completions are generated via Click's
built-in ``shell_completion`` mechanism and written to the appropriate
shell-specific location.

Usage
-----
    promptgenie completion install zsh
    promptgenie completion install bash
    promptgenie completion install fish
    promptgenie completion show zsh      # print without installing
    promptgenie completion status        # check what's installed

Dynamic completions for --template, --target, and context packs are built
by introspecting the installed data files and cached to
``~/.cache/promptgenie/completions.json`` so shell startup stays fast.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

import click

from promptgenie.core.errors import EXIT_OK, EXIT_USAGE
from promptgenie.renderers.rich import console, diag_console

# ---------------------------------------------------------------------------
# Shell profiles
# ---------------------------------------------------------------------------


class _ShellMeta(TypedDict):
    rc_files: list[str]
    completion_dir: str
    filename: str
    env_var: str
    env_value: str
    source_snippet: str | None
    fpath_snippet: str | None


_SHELL_META: dict[str, _ShellMeta] = {
    "zsh": {
        "rc_files": ["~/.zshrc"],
        "completion_dir": "~/.zsh/completions",
        "filename": "_promptgenie",
        "env_var": "_PROMPTGENIE_COMPLETE",
        "env_value": "zsh_source",
        "source_snippet": 'eval "$(_PROMPTGENIE_COMPLETE=zsh_source promptgenie)"',
        "fpath_snippet": "fpath=(~/.zsh/completions $fpath)\nautoload -Uz compinit && compinit",
    },
    "bash": {
        "rc_files": ["~/.bashrc", "~/.bash_profile"],
        "completion_dir": "~/.bash_completion.d",
        "filename": "promptgenie",
        "env_var": "_PROMPTGENIE_COMPLETE",
        "env_value": "bash_source",
        "source_snippet": 'eval "$(_PROMPTGENIE_COMPLETE=bash_source promptgenie)"',
        "fpath_snippet": None,
    },
    "fish": {
        "rc_files": ["~/.config/fish/completions/"],
        "completion_dir": "~/.config/fish/completions",
        "filename": "promptgenie.fish",
        "env_var": "_PROMPTGENIE_COMPLETE",
        "env_value": "fish_source",
        "source_snippet": None,  # fish auto-loads from completions dir
        "fpath_snippet": None,
    },
}

_CACHE_DIR = Path("~/.cache/promptgenie").expanduser()
_CACHE_FILE = _CACHE_DIR / "completions.json"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _build_completion_cache() -> dict:
    """Build a cache of dynamic completion values from installed data files."""
    from promptgenie.core.context_packs import PACKS_DIR
    from promptgenie.core.generator import PROFILES_DIR, TEMPLATES_DIR

    def _stems(directory: Path, suffix: str = ".yaml") -> list[str]:
        try:
            return sorted(p.stem for p in directory.glob(f"*{suffix}"))
        except Exception:
            return []

    cache = {
        "targets": _stems(PROFILES_DIR),
        "templates": _stems(TEMPLATES_DIR),
        "context_packs": _stems(PACKS_DIR),
    }
    return cache


def _write_cache(data: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # cache failure is non-fatal


def _read_cache() -> dict[str, object] | None:
    try:
        if _CACHE_FILE.exists():
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            return dict(data) if isinstance(data, dict) else None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------


def _generate_script(shell: str) -> str | None:
    """Generate the completion script for *shell* using Click's mechanism."""
    meta = _SHELL_META.get(shell)
    if not meta:
        return None

    env = os.environ.copy()
    env[meta["env_var"]] = meta["env_value"]

    try:
        result = subprocess.run(
            ["promptgenie"],
            env=env,
            capture_output=True,
            text=True,
        )
        return result.stdout or None
    except FileNotFoundError:
        # Fallback: try running as a module
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"import os; os.environ['{meta['env_var']}'] = '{meta['env_value']}'; "
                    "from promptgenie.cli import cli; cli(standalone_mode=False)",
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            return result.stdout or None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------


@click.group(name="completion")
def completion_group() -> None:
    """Manage shell tab-completion for PromptGenie."""


@completion_group.command(name="install")
@click.argument("shell", type=click.Choice(["zsh", "bash", "fish"]))
@click.option(
    "--dir",
    "install_dir",
    default=None,
    type=click.Path(),
    help="Override the default installation directory.",
)
@click.option(
    "--no-rc",
    "skip_rc",
    is_flag=True,
    help="Write the completion file only; skip RC file modification.",
)
def install_cmd(shell: str, install_dir: str | None, skip_rc: bool) -> None:
    """Install tab-completion for SHELL (zsh, bash, or fish).

    \b
    After installing, restart your shell or source the RC file:
        zsh:  source ~/.zshrc
        bash: source ~/.bashrc
        fish: (auto-loaded on next shell start)
    """
    meta = _SHELL_META[shell]
    script = _generate_script(shell)

    # Ensure completion cache is up-to-date
    cache = _build_completion_cache()
    _write_cache(cache)
    diag_console.print(f"[dim]Completion cache written to {_CACHE_FILE}[/dim]")

    # Determine target directory and file
    comp_dir = (
        Path(install_dir).expanduser() if install_dir else Path(meta["completion_dir"]).expanduser()
    )
    comp_file = comp_dir / meta["filename"]

    comp_dir.mkdir(parents=True, exist_ok=True)

    if script:
        comp_file.write_text(script, encoding="utf-8")
        console.print(f"[green]✓[/green]  Completion file written to [cyan]{comp_file}[/cyan]")
    else:
        console.print(
            "[yellow]Warning:[/yellow] Could not generate completion script automatically."
        )
        console.print(f"[dim]Add the following to your {meta['rc_files'][0]}:[/dim]")
        console.print(f"  [cyan]{meta['source_snippet']}[/cyan]")

    # RC file modification
    if not skip_rc and shell != "fish":
        rc_path = Path(meta["rc_files"][0]).expanduser()
        _add_to_rc(rc_path, shell, meta, comp_dir)
    elif shell == "fish":
        console.print(
            f"[dim]Fish completions are auto-loaded from {comp_dir} on next shell start.[/dim]"
        )

    console.print(
        f"\n[bold green]Shell completion installed for {shell}.[/bold green]  "
        "Restart your shell or run:"
    )
    if shell == "fish":
        console.print("  [cyan]exec fish[/cyan]")
    else:
        console.print(f"  [cyan]source {meta['rc_files'][0]}[/cyan]")

    sys.exit(EXIT_OK)


@completion_group.command(name="show")
@click.argument("shell", type=click.Choice(["zsh", "bash", "fish"]))
def show_cmd(shell: str) -> None:
    """Print the completion script to stdout without installing it."""
    script = _generate_script(shell)
    if script:
        click.echo(script)
    else:
        meta = _SHELL_META[shell]
        diag_console.print(
            "[yellow]Warning:[/yellow] Could not generate completion script. "
            "Ensure 'promptgenie' is on your PATH."
        )
        diag_console.print("[dim]Fallback: add to your shell RC:[/dim]")
        diag_console.print(f"  {meta['source_snippet']}")
        sys.exit(EXIT_USAGE)


@completion_group.command(name="status")
def status_cmd() -> None:
    """Show which shells have completion installed and cache state."""
    tbl_lines: list[str] = []

    for shell, meta in _SHELL_META.items():
        comp_dir = Path(meta["completion_dir"]).expanduser()
        comp_file = comp_dir / meta["filename"]
        installed = comp_file.exists()
        icon = "[green]✓[/green]" if installed else "[dim]—[/dim]"
        tbl_lines.append(
            f"  {icon}  [bold]{shell}[/bold]  [dim]{comp_file}[/dim]"
            + ("" if installed else "  [dim](not installed)[/dim]")
        )

    cache_state = (
        f"[green]found[/green] [dim]({_CACHE_FILE})[/dim]"
        if _CACHE_FILE.exists()
        else "[dim]not built[/dim]"
    )
    tbl_lines.append(f"\n  Cache: {cache_state}")

    from rich.panel import Panel

    console.print(Panel("\n".join(tbl_lines), title="Completion Status", border_style="dim"))

    sys.exit(EXIT_OK)


@completion_group.command(name="refresh-cache")
def refresh_cache_cmd() -> None:
    """Rebuild the dynamic completion cache (targets, templates, packs)."""
    cache = _build_completion_cache()
    _write_cache(cache)
    console.print(f"[green]✓[/green]  Cache refreshed at [cyan]{_CACHE_FILE}[/cyan]")
    for key, values in cache.items():
        console.print(f"  [dim]{key}:[/dim] {len(values)} items")
    sys.exit(EXIT_OK)


# ---------------------------------------------------------------------------
# RC file helper
# ---------------------------------------------------------------------------


def _add_to_rc(rc_path: Path, shell: str, meta: _ShellMeta, comp_dir: Path) -> None:
    """Append completion activation to the RC file if not already present."""
    snippet = meta.get("source_snippet", "")
    fpath_snippet = meta.get("fpath_snippet", "")
    if not snippet:
        return

    try:
        existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    except OSError:
        existing = ""

    additions: list[str] = []

    if (
        shell == "zsh"
        and fpath_snippet
        and "promptgenie" not in existing
        and "fpath=(~/.zsh/completions" not in existing
    ):
        additions.append(fpath_snippet)

    if snippet not in existing:
        additions.append(snippet)

    if additions:
        block = "\n# PromptGenie shell completion\n" + "\n".join(additions) + "\n"
        try:
            with rc_path.open("a", encoding="utf-8") as f:
                f.write(block)
            console.print(
                f"[green]✓[/green]  Added completion activation to [cyan]{rc_path}[/cyan]"
            )
        except OSError as e:
            console.print(f"[yellow]Warning:[/yellow] Could not write to {rc_path}: {e}")
            console.print(f"[dim]Add manually:[/dim]  {snippet}")
    else:
        console.print(f"[dim]  {rc_path} already contains completion setup — skipped.[/dim]")
