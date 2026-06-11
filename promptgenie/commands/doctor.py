"""doctor.py — self-check command for PromptGenie.

Checks Python version, package installation, config files, optional extras,
shell completion, and provider auth.  Emits remediation commands for anything
that fails so the user knows exactly how to fix each issue.

Exit codes
----------
0  — all checks passed (or only warnings)
1  — one or more checks failed (printed in red with remediation hints)
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

import click

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK
from promptgenie.renderers.rich import console

# ---------------------------------------------------------------------------
# Check result data classes
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    label: str
    passed: bool
    detail: str = ""
    remediation: str = ""
    warning: bool = False  # warning = shown in yellow, doesn't fail the exit code


@dataclass
class CheckGroup:
    title: str
    results: list[CheckResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_python_version() -> CheckResult:
    v = sys.version_info
    label = "Python version"
    detail = f"{v.major}.{v.minor}.{v.micro} ({platform.python_implementation()})"
    if (v.major, v.minor) < (3, 10):
        return CheckResult(
            label=label,
            passed=False,
            detail=detail,
            remediation="Upgrade to Python ≥ 3.10 — https://www.python.org/downloads/",
        )
    return CheckResult(label=label, passed=True, detail=detail)


def _check_package_version() -> CheckResult:
    from importlib.metadata import PackageNotFoundError, version

    try:
        ver = version("promptgenie")
        return CheckResult(label="promptgenie installed", passed=True, detail=f"v{ver}")
    except PackageNotFoundError:
        return CheckResult(
            label="promptgenie installed",
            passed=False,
            detail="not found",
            remediation="pip install promptgenie",
        )


def _check_config_file() -> CheckResult:
    try:
        from promptgenie.core.config import _find_config

        cfg_path = _find_config()
        if cfg_path is None:
            return CheckResult(
                label=".promptgenie.yaml",
                passed=True,
                detail="not found (using defaults)",
                warning=True,
            )
        return CheckResult(
            label=".promptgenie.yaml",
            passed=True,
            detail=f"found at {cfg_path}",
        )
    except Exception as e:
        return CheckResult(
            label=".promptgenie.yaml",
            passed=False,
            detail=str(e),
            remediation="Run `promptgenie validate` to check your config file.",
        )


def _check_extra(package: str, extra_name: str, install_cmd: str) -> CheckResult:
    available = importlib.util.find_spec(package) is not None
    return CheckResult(
        label=f"extra: {extra_name}",
        passed=available,
        detail="installed" if available else "not installed",
        remediation=install_cmd if not available else "",
        warning=not available,  # extras are optional — warn, don't fail
    )


def _check_ollama() -> CheckResult:
    """Check if a local Ollama instance is reachable."""
    import urllib.error
    import urllib.request

    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        from urllib.parse import urlparse

        _scheme = urlparse(base).scheme.lower()
        if _scheme not in ("http", "https"):
            return CheckResult(
                label="Ollama (local provider)",
                passed=False,
                detail=f"OLLAMA_BASE_URL has disallowed scheme {_scheme!r}",
                remediation="Set OLLAMA_BASE_URL to an http:// or https:// URL",
            )
        req = urllib.request.urlopen(f"{base}/api/tags", timeout=2)  # nosec B310 — scheme validated above
        req.close()
        return CheckResult(
            label="Ollama (local provider)",
            passed=True,
            detail=f"reachable at {base}",
        )
    except Exception:
        return CheckResult(
            label="Ollama (local provider)",
            passed=False,
            detail=f"not reachable at {base}",
            remediation="Install from https://ollama.ai or set OLLAMA_BASE_URL",
            warning=True,  # optional provider
        )


def _check_anthropic_key() -> CheckResult:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if has_key:
        return CheckResult(
            label="ANTHROPIC_API_KEY",
            passed=True,
            detail="set",
        )
    return CheckResult(
        label="ANTHROPIC_API_KEY",
        passed=False,
        detail="not set",
        remediation="export ANTHROPIC_API_KEY=sk-ant-...",
        warning=True,  # needed for benchmark/LLM features only
    )


def _check_openai_key() -> CheckResult:
    has_key = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if has_key:
        return CheckResult(
            label="OPENAI_API_KEY",
            passed=True,
            detail="set (used for --llm scan analysis)",
        )
    return CheckResult(
        label="OPENAI_API_KEY",
        passed=False,
        detail="not set",
        remediation="export OPENAI_API_KEY=sk-... (only needed for scan --llm)",
        warning=True,
    )


def _check_completion(shell: str) -> CheckResult:
    from promptgenie.commands.completion import _SHELL_META

    meta = _SHELL_META.get(shell, {})
    if not meta:
        return CheckResult(label=f"{shell} completion", passed=False, detail="unknown shell")

    comp_file = (Path(meta["completion_dir"]) / meta["filename"]).expanduser()
    installed = comp_file.exists()
    return CheckResult(
        label=f"{shell} completion",
        passed=installed,
        detail=str(comp_file) if installed else "not installed",
        remediation=f"promptgenie completion install {shell}" if not installed else "",
        warning=not installed,
    )


def _check_policy_files() -> CheckResult:
    cwd_policy = Path(".promptgenie.policy.yaml")
    home_policy = Path("~/.config/promptgenie/policy.yaml").expanduser()
    found = []
    if cwd_policy.exists():
        found.append(str(cwd_policy))
    if home_policy.exists():
        found.append(str(home_policy))
    if found:
        return CheckResult(
            label="Policy files",
            passed=True,
            detail=", ".join(found),
        )
    return CheckResult(
        label="Policy files",
        passed=False,
        detail="none found",
        remediation="Create .promptgenie.policy.yaml or use promptgenie policy --help",
        warning=True,
    )


def _check_no_color_env() -> CheckResult:
    no_color = "NO_COLOR" in os.environ
    force_color = bool(os.environ.get("FORCE_COLOR", ""))
    if no_color:
        return CheckResult(
            label="Color env vars",
            passed=True,
            detail="NO_COLOR is set — Rich output will be plain text",
            warning=True,
        )
    if force_color:
        return CheckResult(
            label="Color env vars",
            passed=True,
            detail="FORCE_COLOR is set — color always on",
        )
    return CheckResult(label="Color env vars", passed=True, detail="auto-detect via TTY")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_doctor(verbose: bool = False) -> list[CheckGroup]:
    """Run all health checks and return grouped results."""
    detected_shell = Path(os.environ.get("SHELL", "")).name or "bash"

    groups = [
        CheckGroup(
            "Runtime",
            [
                _check_python_version(),
                _check_package_version(),
            ],
        ),
        CheckGroup(
            "Configuration",
            [
                _check_config_file(),
                _check_policy_files(),
                _check_no_color_env(),
            ],
        ),
        CheckGroup(
            "Optional extras",
            [
                _check_extra(
                    "anthropic",
                    "benchmark",
                    "pip install 'promptgenie[benchmark]'",
                ),
                _check_extra(
                    "tiktoken",
                    "tokenizer",
                    "pip install 'promptgenie[tokenizer]'",
                ),
            ],
        ),
        CheckGroup(
            "Providers",
            [
                _check_anthropic_key(),
                _check_openai_key(),
                _check_ollama(),
            ],
        ),
        CheckGroup(
            "Shell completion",
            [_check_completion(detected_shell)],
        ),
    ]

    return groups


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command(name="doctor")
@click.option("--verbose", "-v", is_flag=True, help="Show all checks including passing ones.")
@click.option(
    "--format",
    "output_format",
    default="rich",
    type=click.Choice(["rich", "json"]),
    help="Output format.",
)
def doctor_cmd(verbose: bool, output_format: str) -> None:
    """Run a self-check — Python version, config, providers, extras, shell completion."""
    groups = run_doctor(verbose=verbose)

    all_results = [r for g in groups for r in g.results]
    hard_failures = [r for r in all_results if not r.passed and not r.warning]

    if output_format == "json":
        import json as _json

        data = {
            "schema_version": "1.0",
            "tool": "promptgenie",
            "command": "doctor",
            "version": _try_version(),
            "passed": len(hard_failures) == 0,
            "failure_count": len(hard_failures),
            "warning_count": sum(1 for r in all_results if not r.passed and r.warning),
            "groups": [
                {
                    "title": g.title,
                    "checks": [
                        {
                            "label": r.label,
                            "passed": r.passed,
                            "warning": r.warning,
                            "detail": r.detail,
                            "remediation": r.remediation,
                        }
                        for r in g.results
                    ],
                }
                for g in groups
            ],
        }
        click.echo(_json.dumps(data, indent=2))
        sys.exit(EXIT_OK if not hard_failures else EXIT_FAILURE)

    # ── Rich output ──────────────────────────────────────────────────────
    from rich.panel import Panel

    console.print()
    console.print(
        Panel(
            f"[bold]promptgenie doctor[/bold]  v{_try_version()}",
            border_style="blue",
        )
    )

    for group in groups:
        # Skip groups where all checks pass unless verbose
        if not verbose and all(r.passed for r in group.results):
            show_header = any(r.warning for r in group.results)
            if not show_header:
                continue

        console.print(f"\n  [bold dim]{group.title}[/bold dim]")
        for r in group.results:
            if r.passed and not r.warning:
                if verbose:
                    console.print(f"    [green]✓[/green]  {r.label}  [dim]{r.detail}[/dim]")
            elif r.passed and r.warning:
                console.print(f"    [yellow]⚠[/yellow]  {r.label}  [dim]{r.detail}[/dim]")
            else:
                console.print(f"    [red]✗[/red]  [bold]{r.label}[/bold]  [dim]{r.detail}[/dim]")
                if r.remediation:
                    console.print(f"         [dim]→ {r.remediation}[/dim]")

    console.print()
    if hard_failures:
        console.print(
            f"[red bold]{len(hard_failures)} check(s) failed.[/red bold]  "
            "Fix the issues above and re-run [cyan]promptgenie doctor[/cyan]."
        )
        sys.exit(EXIT_FAILURE)
    else:
        warnings = sum(1 for r in all_results if not r.passed and r.warning)
        if warnings:
            console.print(
                f"[yellow]All required checks passed[/yellow] with {warnings} optional warning(s)."
            )
        else:
            console.print("[green bold]All checks passed.[/green bold]")
        sys.exit(EXIT_OK)


def _try_version() -> str:
    try:
        from importlib.metadata import version

        return version("promptgenie")
    except Exception:
        return "unknown"
