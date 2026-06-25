"""palette_cmd.py — ``promptgenie palette`` smart command palette.

A keyboard-driven fuzzy finder (built with Textual) that lets you search
across all PromptGenie commands, templates, profiles, packs, recent history
entries, and recent evaluation runs.  Selecting an entry prints the
equivalent CLI command so you can run it or pipe it to your shell.

Requires: pip install 'promptgenie[tui]'

Keyboard shortcuts
------------------
  Type        — filter items
  Up / Down   — navigate
  Enter       — confirm selection (echoes CLI command)
  Escape / Q  — quit without selection

Examples
--------
  promptgenie palette
  eval $(promptgenie palette)   # run the selected command
"""

from __future__ import annotations

from dataclasses import dataclass

import click

from promptgenie.core.errors import EXIT_OK
from promptgenie.renderers.rich import console, diag_console

# ---------------------------------------------------------------------------
# Palette item catalogue
# ---------------------------------------------------------------------------


@dataclass
class PaletteItem:
    label: str  # shown in the list
    kind: str  # command | template | profile | pack | history | eval
    command: str  # CLI command to emit on selection
    description: str = ""


def _build_catalogue() -> list[PaletteItem]:
    items: list[PaletteItem] = []

    # ── Built-in commands ─────────────────────────────────────────────────
    _COMMANDS = [
        ("lint <file>", "command", "promptgenie lint", "Lint a prompt file"),
        ("scan <file>", "command", "promptgenie scan", "Scan for security issues"),
        ("run <spec>", "command", "promptgenie run", "Run a PromptSpec"),
        ("analyze <file>", "command", "promptgenie analyze", "Deep analysis of a prompt"),
        ("evaluate <file>", "command", "promptgenie evaluate", "Multi-model evaluation"),
        ("eval init", "command", "promptgenie eval init", "Scaffold an eval suite"),
        ("eval run", "command", "promptgenie eval run", "Run an eval suite"),
        ("eval compare", "command", "promptgenie eval compare", "Compare to snapshot"),
        ("eval approve", "command", "promptgenie eval approve", "Approve snapshot"),
        ("history list", "command", "promptgenie history list", "List run history"),
        ("history show", "command", "promptgenie history show", "Show a history entry"),
        ("history diff", "command", "promptgenie history diff", "Diff two history entries"),
        ("history export", "command", "promptgenie history export", "Export history"),
        ("template list", "command", "promptgenie template list", "List templates"),
        ("template new", "command", "promptgenie template new", "Create a template"),
        ("template render", "command", "promptgenie template render", "Render a template"),
        ("lock <spec>", "command", "promptgenie lock", "Create a prompt lockfile"),
        ("lock --check", "command", "promptgenie lock --check", "Verify a lockfile"),
        ("watch <dir>", "command", "promptgenie watch", "Watch for prompt changes"),
        ("plugin list", "command", "promptgenie plugin list", "List installed plugins"),
        ("plugin scaffold", "command", "promptgenie plugin scaffold", "Scaffold a plugin stub"),
        ("pack list", "command", "promptgenie pack list", "List packs"),
        ("pack install", "command", "promptgenie pack install", "Install a pack"),
        ("pack diff", "command", "promptgenie pack diff", "Diff two pack versions"),
        ("pack promote", "command", "promptgenie pack promote", "Promote a pack env"),
        ("pack test", "command", "promptgenie pack test", "Run pack unit tests"),
        ("wizard", "command", "promptgenie wizard", "Guided prompt builder"),
        ("tui", "command", "promptgenie tui", "Open full-screen TUI"),
        ("auth login", "command", "promptgenie auth login", "Configure API key"),
        ("auth status", "command", "promptgenie auth status", "Show auth status"),
    ]
    for label, kind, cmd, desc in _COMMANDS:
        items.append(PaletteItem(label=label, kind=kind, command=cmd, description=desc))

    # ── Templates ─────────────────────────────────────────────────────────
    try:
        from promptgenie.core.template_store import list_all_templates

        for tmpl in list_all_templates():
            items.append(
                PaletteItem(
                    label=f"template: {tmpl.name}",
                    kind="template",
                    command=f"promptgenie template render {tmpl.id}",
                    description=tmpl.description or "",
                )
            )
    except Exception:
        pass

    # ── Packs ─────────────────────────────────────────────────────────────
    try:
        from promptgenie.core.context_packs import list_packs

        for pack in list_packs():
            pid = pack.get("id", "")
            items.append(
                PaletteItem(
                    label=f"pack: {pid}",
                    kind="pack",
                    command=f"promptgenie pack install {pid}",
                    description=pack.get("description", ""),
                )
            )
    except Exception:
        pass

    # ── Recent history ────────────────────────────────────────────────────
    try:
        from promptgenie.core.history_db import open_history_db

        with open_history_db() as db:
            for record in db.list_runs(limit=20):
                short_id = record.id[:8]
                items.append(
                    PaletteItem(
                        label=f"history: {short_id} {record.spec_name or record.provider}",
                        kind="history",
                        command=f"promptgenie history show {short_id}",
                        description=f"{record.provider}/{record.model}  {record.started_at[:10]}",
                    )
                )
    except Exception:
        pass

    return items


# ---------------------------------------------------------------------------
# Fuzzy filtering (no dependency)
# ---------------------------------------------------------------------------


def _fuzzy_match(query: str, text: str) -> bool:
    """True if every character of *query* appears in order in *text*."""
    if not query:
        return True
    q = query.lower()
    t = text.lower()
    idx = 0
    for ch in q:
        found = t.find(ch, idx)
        if found == -1:
            return False
        idx = found + 1
    return True


def _filter_items(items: list[PaletteItem], query: str) -> list[PaletteItem]:
    return [
        it for it in items if _fuzzy_match(query, it.label) or _fuzzy_match(query, it.description)
    ]


# ---------------------------------------------------------------------------
# Textual TUI implementation
# ---------------------------------------------------------------------------


def _run_palette_tui(items: list[PaletteItem]) -> str | None:
    """Return the selected command string, or None if cancelled."""
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.reactive import reactive
    from textual.widgets import Footer, Header, Input, Label, ListItem, ListView

    selected_command: list[str | None] = [None]  # mutable container for closure

    class PaletteApp(App):
        CSS = """
        Screen { layout: vertical; }
        #search-bar { height: 3; border: solid $accent; margin: 1; }
        #result-list { height: 1fr; }
        ListItem { padding: 0 1; }
        ListItem:hover { background: $accent 20%; }
        ListItem.--highlight { background: $accent 40%; }
        #status-bar { height: 1; background: $surface; color: $text-muted; }
        .kind-command  { color: $success; }
        .kind-template { color: $warning; }
        .kind-pack     { color: $primary; }
        .kind-history  { color: $text-muted; }
        """

        BINDINGS = [
            Binding("escape", "quit_no_select", "Quit", show=True),
            Binding("enter", "confirm", "Select", show=True),
        ]

        # NB: not named `query` — that shadows textual's DOMNode.query() method.
        query_text: reactive[str] = reactive("")

        def __init__(self, catalogue: list[PaletteItem]) -> None:
            super().__init__()
            self._catalogue = catalogue
            self._filtered = list(catalogue)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Input(placeholder="Type to filter commands, templates, packs…", id="search-bar")
            yield ListView(id="result-list")
            yield Label("", id="status-bar")
            yield Footer()

        def on_mount(self) -> None:
            self._refresh_list()
            self.query_one("#search-bar", Input).focus()

        def on_input_changed(self, event: Input.Changed) -> None:
            self.query_text = event.value
            self._filtered = _filter_items(self._catalogue, event.value)
            self._refresh_list()

        def _refresh_list(self) -> None:
            lv = self.query_one("#result-list", ListView)
            lv.clear()
            for item in self._filtered[:80]:
                kind_css = f"kind-{item.kind}"
                lv.append(
                    ListItem(
                        Label(
                            f"[{kind_css}][{item.kind}][/{kind_css}] {item.label}  "
                            f"[dim]{item.description[:60]}[/dim]",
                            markup=True,
                        ),
                    )
                )
            status = self.query_one("#status-bar", Label)
            status.update(f" {len(self._filtered)} items  |  Enter=select  Esc=quit")

        def action_confirm(self) -> None:
            lv = self.query_one("#result-list", ListView)
            idx = lv.index
            if idx is not None and 0 <= idx < len(self._filtered):
                selected_command[0] = self._filtered[idx].command
            self.exit()

        def action_quit_no_select(self) -> None:
            self.exit()

    PaletteApp(items).run()
    return selected_command[0]


# ---------------------------------------------------------------------------
# Fallback: simple readline-style picker (no Textual)
# ---------------------------------------------------------------------------


def _run_palette_readline(items: list[PaletteItem]) -> str | None:
    """Simple terminal picker used when Textual is not installed."""
    console.print("[bold cyan]PromptGenie Palette[/bold cyan]  — type to filter, Enter to select\n")
    query = click.prompt("Filter", default="")
    filtered = _filter_items(items, query)
    if not filtered:
        console.print("[yellow]No matches.[/yellow]")
        return None
    for i, it in enumerate(filtered[:30], 1):
        console.print(f"  [dim]{i:2}.[/dim] [{it.kind}] {it.label}  [dim]{it.description}[/dim]")
    choice = click.prompt("Select number (0 to cancel)", default=0)
    if choice == 0 or choice > len(filtered):
        return None
    return filtered[choice - 1].command  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("palette")
@click.option("--no-tui", is_flag=True, help="Use readline fallback instead of Textual TUI.")
@click.option("--print-only", is_flag=True, help="Only print selection, do not run it.")
def palette_cmd(no_tui: bool, print_only: bool) -> None:
    """Fuzzy command palette for PromptGenie.

    Searches commands, templates, packs, and recent history.
    Prints the selected CLI command so you can pipe it or run it.

    \b
    Examples:
      promptgenie palette
      eval $(promptgenie palette --print-only)
    """
    catalogue = _build_catalogue()

    selected: str | None = None

    if no_tui:
        selected = _run_palette_readline(catalogue)
    else:
        try:
            from textual.app import App  # noqa: F401

            selected = _run_palette_tui(catalogue)
        except ImportError:
            diag_console.print(
                "[yellow]Textual not installed — using simple fallback.[/yellow]\n"
                "Install the TUI extra: [bold]pip install 'promptgenie[tui]'[/bold]\n"
            )
            selected = _run_palette_readline(catalogue)

    if selected is None:
        raise SystemExit(EXIT_OK)

    if print_only:
        click.echo(selected)
    else:
        console.print(f"\n[bold]Selected:[/bold] {selected}\n")
        click.echo(selected)

    raise SystemExit(EXIT_OK)
