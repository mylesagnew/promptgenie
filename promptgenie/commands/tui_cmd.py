"""tui_cmd.py — ``promptgenie tui`` command.

Launches the full-screen Textual TUI when the ``textual`` package is
installed (``pip install 'promptgenie[tui]'``).  When Textual is not
available, prints an informative error and falls back gracefully.

TUI layout
----------
  Header bar: title + current file name + status
  Left pane (35%): tree of recent files / recent evaluations
  Main pane (65%): TextArea for the prompt
  Bottom findings panel: lint issues + scan findings (live)
  Status bar: score | tokens | cost | provider | model

Keyboard shortcuts
------------------
  Ctrl+S   Save current prompt to file
  Ctrl+R   Run (send to provider)
  Ctrl+D   Diff against last saved version
  Ctrl+L   Lint current prompt
  Ctrl+T   Test against eval suite (if one exists)
  Ctrl+Q   Quit

The TUI is a thin shell: all business logic is delegated to
core.linter, core.scanner, core.run_engine, core.eval_suite etc.
"""

from __future__ import annotations

import click

from promptgenie.core.errors import EXIT_OK, EXIT_USAGE
from promptgenie.renderers.rich import diag_console

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


@click.command("tui")
@click.argument("file", default=None, required=False, metavar="[FILE]", type=click.Path())
@click.option("--provider", "-p", default=None, help="Provider to use for --run.")
@click.option("--model", default=None, help="Model override.")
@click.option("--read-only", is_flag=True, help="Open in read-only mode (no save/run).")
def tui_cmd(file: str | None, provider: str | None, model: str | None, read_only: bool) -> None:
    """Launch the full-screen prompt engineering TUI.

    Requires: pip install 'promptgenie[tui]'

    \b
    Examples:
      promptgenie tui
      promptgenie tui prompts/auth.md
      promptgenie tui prompts/auth.md --provider claude
    """
    try:
        from textual.app import App  # noqa: F401  # verify import
    except ImportError:
        diag_console.print(
            "[red]Error:[/red] Textual is not installed.\n"
            "Install the TUI extra with: [bold]pip install 'promptgenie[tui]'[/bold]"
        )
        raise SystemExit(EXIT_USAGE) from None

    _run_tui(file=file, provider=provider, model=model, read_only=read_only)
    raise SystemExit(EXIT_OK)


# ---------------------------------------------------------------------------
# Textual application
# ---------------------------------------------------------------------------


def _run_tui(
    *,
    file: str | None,
    provider: str | None,
    model: str | None,
    read_only: bool,
) -> None:
    """Build and run the Textual app (only called when textual is available)."""
    build_tui_app(file=file, provider=provider, model=model, read_only=read_only).run()


def build_tui_app(
    *,
    file: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    read_only: bool = False,
):  # returns a textual App instance
    """Construct (but do not run) the PromptGenie Textual app.

    Importing textual is deferred to call time so the rest of the CLI works
    without the ``[tui]`` extra. Returning the app (rather than running it)
    makes the TUI drivable from tests via ``app.run_test()``.
    """
    from pathlib import Path

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.reactive import reactive
    from textual.widgets import (
        Footer,
        Header,
        RichLog,
        Static,
        TextArea,
        Tree,
    )

    class PromptGenieApp(App):
        """PromptGenie full-screen TUI."""

        CSS = """
        Screen {
            layout: vertical;
        }
        #pane-row {
            height: 1fr;
            layout: horizontal;
        }
        #file-tree {
            width: 30;
            border-right: solid $accent;
        }
        #editor-pane {
            width: 1fr;
            layout: vertical;
        }
        #editor {
            height: 1fr;
        }
        #findings-panel {
            height: 10;
            border-top: solid $accent;
            overflow-y: auto;
        }
        #status-bar {
            height: 1;
            background: $surface;
            color: $text-muted;
        }
        """

        BINDINGS = [
            Binding("ctrl+s", "save", "Save", show=True),
            Binding("ctrl+r", "run_prompt", "Run", show=True),
            Binding("ctrl+l", "lint_prompt", "Lint", show=True),
            Binding("ctrl+d", "diff_prompt", "Diff", show=True),
            Binding("ctrl+t", "test_prompt", "Test", show=True),
            Binding("ctrl+q", "quit", "Quit", show=True),
        ]

        # Reactive status line fields
        score: reactive[int] = reactive(0)
        token_count: reactive[int] = reactive(0)
        current_file: reactive[str] = reactive("")

        def __init__(self) -> None:
            super().__init__()
            self._file: Path | None = Path(file) if file else None
            self._provider = provider
            self._model = model
            self._read_only = read_only
            self._last_saved: str = ""

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="pane-row"):
                yield Tree("Recent Files", id="file-tree")
                with Vertical(id="editor-pane"):
                    yield TextArea(
                        id="editor",
                        language="markdown",
                        read_only=read_only,
                    )
                    yield RichLog(id="findings-panel", markup=True, highlight=True)
            yield Static(id="status-bar")
            yield Footer()

        def on_mount(self) -> None:
            # Load file if provided
            editor = self.query_one("#editor", TextArea)
            if self._file and self._file.exists():
                content = self._file.read_text(encoding="utf-8")
                editor.load_text(content)
                self._last_saved = content
                self.current_file = str(self._file)
            # Populate file tree with recent files
            tree = self.query_one("#file-tree", Tree)
            tree.root.expand()
            for p in sorted(Path(".").glob("**/*.md"))[:10]:
                tree.root.add_leaf(str(p))
            self._update_status()

        def _update_status(self) -> None:
            editor = self.query_one("#editor", TextArea)
            content = editor.text
            words = len(content.split())
            self.token_count = words
            status = self.query_one("#status-bar", Static)
            fname = self.current_file or "(unsaved)"
            prov = f"{self._provider or 'no provider'}/{self._model or 'default'}"
            status.update(f" {fname}  |  ~{words} tokens  |  score: {self.score}  |  {prov}")

        def on_text_area_changed(self) -> None:
            self._update_status()

        # ── Actions ──────────────────────────────────────────────────────────

        def action_save(self) -> None:
            if self._read_only:
                return
            editor = self.query_one("#editor", TextArea)
            content = editor.text
            if self._file is None:
                self._file = Path("prompt.md")
                self.current_file = str(self._file)
            self._file.write_text(content, encoding="utf-8")
            self._last_saved = content
            log = self.query_one("#findings-panel", RichLog)
            log.write(f"[green]✓ Saved → {self._file}[/green]")

        def action_lint_prompt(self) -> None:
            editor = self.query_one("#editor", TextArea)
            log = self.query_one("#findings-panel", RichLog)
            log.clear()
            from promptgenie.core.linter import lint

            result = lint(editor.text)
            self.score = result.score
            self._update_status()
            log.write(f"[bold]Lint:[/bold] score {result.score}/100  {len(result.issues)} issue(s)")
            for issue in result.issues[:20]:
                color = "red" if issue.severity == "HIGH" else "yellow"
                log.write(f"  [{color}]{issue.severity}[/{color}] {issue.code}  {issue.message}")
            if not result.issues:
                log.write("[green]No lint issues.[/green]")

        def action_run_prompt(self) -> None:
            if self._read_only or not self._provider:
                log = self.query_one("#findings-panel", RichLog)
                log.write("[yellow]No provider configured. Use --provider flag.[/yellow]")
                return
            log = self.query_one("#findings-panel", RichLog)
            log.write(f"[blue]Running via {self._provider}/{self._model or 'default'}…[/blue]")
            # In a real implementation this would be a Textual worker
            log.write("[dim](Run not implemented in offline TUI demo)[/dim]")

        def action_diff_prompt(self) -> None:
            editor = self.query_one("#editor", TextArea)
            log = self.query_one("#findings-panel", RichLog)
            current = editor.text
            if current == self._last_saved:
                log.write("[green]No changes since last save.[/green]")
                return
            import difflib

            diff = list(
                difflib.unified_diff(
                    self._last_saved.splitlines(keepends=True),
                    current.splitlines(keepends=True),
                    fromfile="saved",
                    tofile="current",
                )
            )
            log.clear()
            for line in diff[:40]:
                if line.startswith("+"):
                    log.write(f"[green]{line.rstrip()}[/green]")
                elif line.startswith("-"):
                    log.write(f"[red]{line.rstrip()}[/red]")
                else:
                    log.write(f"[dim]{line.rstrip()}[/dim]")

        def action_test_prompt(self) -> None:
            log = self.query_one("#findings-panel", RichLog)
            # Look for adjacent eval suite
            if self._file:
                suite_path = self._file.with_suffix(".eval.yaml")
                if suite_path.exists():
                    from promptgenie.core.eval_suite import load_eval_suite, run_eval_suite

                    suite = load_eval_suite(suite_path)
                    result = run_eval_suite(suite, dry_run=True)
                    log.write(f"[bold]Eval:[/bold] {result.pass_count}/{result.total} passed")
                    return
            log.write("[dim]No adjacent .eval.yaml found. Create one to enable Ctrl+T.[/dim]")

    return PromptGenieApp()
