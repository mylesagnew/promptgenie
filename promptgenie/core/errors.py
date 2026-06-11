"""errors.py — centralized exit codes and error handling for PromptGenie.

Exit code contract
-----------------
  0   OK            — clean run, no findings, tests pass, policy passed
  1   FAILURE       — lint/scan/policy findings exceeded threshold, or test failures
  2   USAGE         — bad arguments, missing / invalid config, unknown flag, unresolved
                      required variable
  3   PROVIDER      — provider / network failure (API unavailable, auth error, timeout
                      on remote call)
  4   TEMPLATE      — unknown template, unknown target profile, template render error
  5   TEST          — dedicated code for ``promptgenie test`` assertion failures
  6   SECRETS       — pre-send secrets gate triggered (not yet wired up everywhere, but
                      reserved so callers can detect it)
  7   TIMEOUT       — operation exceeded --timeout limit
  130 INTERRUPTED   — KeyboardInterrupt / SIGINT
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# Exit code constants
# ---------------------------------------------------------------------------

EXIT_OK: int = 0
EXIT_FAILURE: int = 1  # findings / threshold exceeded
EXIT_USAGE: int = 2  # bad args, config, unresolved vars
EXIT_PROVIDER: int = 3  # provider / network failure
EXIT_TEMPLATE: int = 4  # template / profile error
EXIT_TEST: int = 5  # test assertion failures
EXIT_SECRETS: int = 6  # secrets gate triggered
EXIT_TIMEOUT: int = 7  # operation timed out
EXIT_INTERRUPTED: int = 130  # SIGINT / KeyboardInterrupt


# ---------------------------------------------------------------------------
# PromptGenieError
# ---------------------------------------------------------------------------


class PromptGenieError(Exception):
    """Raised by core / command code to signal a controlled failure.

    Carry an *exit_code* so the top-level handler can map it directly to
    ``sys.exit()``.

    Parameters
    ----------
    message:
        Human-readable error message (no Rich markup — the handler adds it).
    code:
        One of the ``EXIT_*`` constants above. Defaults to ``EXIT_USAGE`` (2)
        because most raise sites are argument / config problems.
    hint:
        Optional one-line suggestion shown after the error, e.g.
        "Use --best-effort to fall back to defaults."
    """

    def __init__(
        self,
        message: str,
        code: int = EXIT_USAGE,
        hint: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint


# ---------------------------------------------------------------------------
# Centralized error handler
# ---------------------------------------------------------------------------


def handle_error(exc: PromptGenieError, *, use_stderr: bool = True) -> None:
    """Print *exc* to stderr (or stdout) and exit with ``exc.code``.

    This is the **only** place ``sys.exit`` should be called for controlled
    errors — command handlers raise ``PromptGenieError``, the top-level
    ``try/except`` catches it and calls this function.

    Parameters
    ----------
    exc:
        The error to display and exit for.
    use_stderr:
        If True (default), write to stderr so the error never pollutes
        structured stdout output (JSON / SARIF pipelines).
    """
    import click

    label = _code_label(exc.code)
    msg = f"[red]{label}:[/red] {exc}"

    # Always use stderr to avoid polluting piped JSON/SARIF output
    from rich.console import Console

    err_console = Console(stderr=use_stderr)
    err_console.print(msg)
    if exc.hint:
        err_console.print(f"[dim]{exc.hint}[/dim]")

    raise SystemExit(exc.code)


def _code_label(code: int) -> str:
    return {
        EXIT_OK: "OK",
        EXIT_FAILURE: "Failure",
        EXIT_USAGE: "Error",
        EXIT_PROVIDER: "Provider error",
        EXIT_TEMPLATE: "Template error",
        EXIT_TEST: "Test failure",
        EXIT_SECRETS: "Secrets blocked",
        EXIT_TIMEOUT: "Timeout",
        EXIT_INTERRUPTED: "Interrupted",
    }.get(code, "Error")


# ---------------------------------------------------------------------------
# Signal handler helper
# ---------------------------------------------------------------------------


def install_interrupt_handler() -> None:
    """Register a SIGINT handler that exits with EXIT_INTERRUPTED (130).

    Call once from the CLI entry point. Without this, a Ctrl-C would exit
    with code 1 (Click's default), violating the exit code contract.
    """
    import signal

    def _handler(signum: int, frame: object) -> None:  # pragma: no cover
        sys.exit(EXIT_INTERRUPTED)

    signal.signal(signal.SIGINT, _handler)
