"""config_cmd.py — ``promptgenie config`` command group.

Commands
--------
  promptgenie config show              show current effective config
  promptgenie config set <key> <val>   set a config value in .promptgenie.yaml
  promptgenie config get <key>         get a config value
  promptgenie config validate          validate .promptgenie.yaml against the workspace schema
  promptgenie config init              scaffold a new .promptgenie.yaml with schema pointer
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from promptgenie.core.errors import EXIT_USAGE
from promptgenie.renderers.rich import console, diag_console

EXIT_INVALID = 1

_CONFIG_FILE = Path(".promptgenie.yaml")

# Supported dot-notation keys and their types
_KNOWN_KEYS: dict[str, type] = {
    "security.airgap": bool,
    "security.block_secrets": bool,
    "security.redact_secrets": bool,
    "routing.default": str,
}


@click.group("config", help="View and modify project configuration.")
def config_group() -> None:
    pass


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


@config_group.command("show")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json", "yaml"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def config_show_cmd(output_format: str) -> None:
    """Show the current effective configuration.

    Example:
      promptgenie config show
      promptgenie config show --format json
    """
    from promptgenie.core.config import load_config

    try:
        cfg = load_config()
    except Exception as exc:
        diag_console.print(f"[red]Config error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from None

    data = {
        "security": {
            "airgap": cfg.security.airgap,
            "block_secrets": cfg.security.block_secrets,
            "redact_secrets": cfg.security.redact_secrets,
        },
        "routing": {
            "default": cfg.routing.default,
            "rules": [{"if": r.condition, "provider": r.provider} for r in cfg.routing.rules],
        },
    }

    if output_format == "json":
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
    elif output_format == "yaml":
        sys.stdout.write(yaml.dump(data, default_flow_style=False))
    else:
        console.print("[bold]Effective Configuration[/bold]")
        console.print(f"  [cyan]security.airgap[/cyan]        = {cfg.security.airgap}")
        console.print(f"  [cyan]security.block_secrets[/cyan] = {cfg.security.block_secrets}")
        console.print(f"  [cyan]security.redact_secrets[/cyan]= {cfg.security.redact_secrets}")
        console.print(f"  [cyan]routing.default[/cyan]        = {cfg.routing.default or '(none)'}")
        if cfg.routing.rules:
            console.print("  [cyan]routing.rules[/cyan]:")
            for r in cfg.routing.rules:
                console.print(f"    if: {r.condition!r} → provider: {r.provider}")


# ---------------------------------------------------------------------------
# config set
# ---------------------------------------------------------------------------


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set_cmd(key: str, value: str) -> None:
    """Set a configuration key in .promptgenie.yaml.

    Creates the file if it does not exist.

    \b
    Supported keys:
      security.airgap           true | false
      security.block_secrets    true | false
      security.redact_secrets   true | false
      routing.default           <provider-name>

    \b
    Examples:
      promptgenie config set security.airgap true
      promptgenie config set routing.default ollama
      promptgenie config set security.block_secrets true
    """
    if key not in _KNOWN_KEYS:
        diag_console.print(
            f"[red]Unknown key:[/red] {key!r}\nSupported: {', '.join(sorted(_KNOWN_KEYS))}"
        )
        raise SystemExit(EXIT_USAGE)

    key_type = _KNOWN_KEYS[key]
    if key_type is bool:
        if value.lower() in ("true", "1", "yes"):
            typed_value: object = True
        elif value.lower() in ("false", "0", "no"):
            typed_value = False
        else:
            diag_console.print(
                f"[red]Invalid value for boolean key {key!r}:[/red] {value!r}. Use true or false."
            )
            raise SystemExit(EXIT_USAGE)
    else:
        typed_value = value

    # Load existing config YAML (raw dict)
    existing: dict = {}
    if _CONFIG_FILE.exists():
        try:
            raw = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except Exception:
            pass

    # Set the nested key
    parts = key.split(".")
    node = existing
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = typed_value

    _CONFIG_FILE.write_text(
        yaml.dump(existing, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    console.print(
        f"[green]✓[/green] Set [cyan]{key}[/cyan] = [bold]{typed_value}[/bold] in {_CONFIG_FILE}"
    )

    if key == "security.airgap" and typed_value:
        console.print(
            "[yellow]Air-gap mode enabled.[/yellow] "
            "External provider calls will be blocked. Local providers (Ollama etc.) still work."
        )


# ---------------------------------------------------------------------------
# config get
# ---------------------------------------------------------------------------


@config_group.command("get")
@click.argument("key")
def config_get_cmd(key: str) -> None:
    """Get the current value of a configuration key.

    Example:
      promptgenie config get security.airgap
    """
    from promptgenie.core.config import load_config

    try:
        cfg = load_config()
    except Exception as exc:
        diag_console.print(f"[red]Config error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from None

    # Resolve nested attribute from cfg
    attr_map = {
        "security.airgap": cfg.security.airgap,
        "security.block_secrets": cfg.security.block_secrets,
        "security.redact_secrets": cfg.security.redact_secrets,
        "routing.default": cfg.routing.default,
    }
    if key not in attr_map:
        diag_console.print(f"[red]Unknown key:[/red] {key!r}")
        raise SystemExit(EXIT_USAGE)

    sys.stdout.write(str(attr_map[key]) + "\n")


# ---------------------------------------------------------------------------
# config validate
# ---------------------------------------------------------------------------

_SCHEMA_URL = "https://promptgenie.dev/schemas/workspace.schema.json"


@config_group.command("validate")
@click.option(
    "--config",
    "config_path",
    default=None,
    metavar="PATH",
    help="Path to config file (default: auto-discover .promptgenie.yaml).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def config_validate_cmd(config_path: str | None, output_format: str) -> None:
    """Validate .promptgenie.yaml against the workspace schema.

    Exits 0 if the file is valid (warnings are printed but do not fail).
    Exits 1 if there are schema errors.
    Exits 2 if the config file is missing or unreadable.

    \b
    Examples:
      promptgenie config validate
      promptgenie config validate --config path/to/.promptgenie.yaml
      promptgenie config validate --format json
    """
    from promptgenie.core.config import _find_config, validate_workspace_config
    from promptgenie.core.fileio import safe_read_yaml

    if config_path is not None:
        path = Path(config_path)
        if not path.exists():
            if output_format == "json":
                sys.stdout.write(
                    json.dumps(
                        {
                            "valid": False,
                            "errors": [f"File not found: {config_path}"],
                            "warnings": [],
                        },
                        indent=2,
                    )
                    + "\n"
                )
            else:
                diag_console.print(f"[red]Error:[/red] File not found: {config_path}")
            raise SystemExit(EXIT_USAGE)
    else:
        found = _find_config()
        if found is None:
            if output_format == "json":
                sys.stdout.write(
                    json.dumps(
                        {
                            "valid": False,
                            "errors": [
                                "No .promptgenie.yaml found in current directory or parents."
                            ],
                            "warnings": [],
                        },
                        indent=2,
                    )
                    + "\n"
                )
            else:
                diag_console.print(
                    "[yellow]No .promptgenie.yaml found.[/yellow] "
                    "Run [bold]promptgenie config init[/bold] to create one."
                )
            raise SystemExit(EXIT_USAGE)
        path = found

    try:
        raw = safe_read_yaml(path) or {}
    except Exception as exc:
        if output_format == "json":
            sys.stdout.write(
                json.dumps(
                    {"valid": False, "errors": [f"YAML parse error: {exc}"], "warnings": []},
                    indent=2,
                )
                + "\n"
            )
        else:
            diag_console.print(f"[red]YAML parse error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from None

    errors, warnings = validate_workspace_config(raw)
    valid = len(errors) == 0

    if output_format == "json":
        sys.stdout.write(
            json.dumps(
                {"valid": valid, "file": str(path), "errors": errors, "warnings": warnings},
                indent=2,
            )
            + "\n"
        )
    else:
        console.print(f"[bold]Validating:[/bold] {path}")
        if warnings:
            for w in warnings:
                console.print(f"  [yellow]warning:[/yellow] {w}")
        if errors:
            for e in errors:
                console.print(f"  [red]error:[/red]   {e}")
            console.print(f"\n[red]✗[/red] {len(errors)} error(s) found.")
        else:
            console.print("[green]✓[/green] Config is valid.")
            if warnings:
                console.print(f"  {len(warnings)} warning(s) — review above.")

    if not valid:
        raise SystemExit(EXIT_INVALID)


# ---------------------------------------------------------------------------
# config init
# ---------------------------------------------------------------------------

_INIT_TEMPLATE = """\
# yaml-language-server: $schema={schema_url}
$schema: "{schema_url}"

workspace:
  name: "{project_name}"
  # version: "1.0"
  # team: "your-team"
  # description: "What this workspace is for."
  # policy: ".promptgenie-policy.yaml"

# defaults:
#   provider: anthropic
#   model: claude-opus-4-5
#   target: claude-code

security:
  airgap: false
  block_secrets: false
  redact_secrets: false

# routing:
#   default: anthropic
#   rules:
#     - if: classification == confidential
#       provider: ollama
#     - if: contains_secrets
#       provider: ollama
#     - if: "*"
#       provider: anthropic

# scanner:
#   disabled_rules: []
#   severity_overrides:
#     PERM_001: HIGH
#   allowlist:
#     - phrase: "example-safe-token"
#       reason: "Test fixture — not a real secret"
#       # expires: "2026-12-31"

# linter:
#   disabled_rules: []
#   custom_vague_verbs:
#     - "handle"
"""


@config_group.command("init")
@click.option(
    "--name",
    default=None,
    metavar="NAME",
    help="Workspace name written into the file (default: current directory name).",
)
@click.option(
    "--force", is_flag=True, default=False, help="Overwrite an existing .promptgenie.yaml."
)
def config_init_cmd(name: str | None, force: bool) -> None:
    """Scaffold a new .promptgenie.yaml with the workspace schema pointer.

    Creates .promptgenie.yaml in the current directory. Refuses to overwrite
    an existing file unless --force is passed.

    \b
    Examples:
      promptgenie config init
      promptgenie config init --name "my-project"
      promptgenie config init --force
    """
    dest = Path(".promptgenie.yaml")
    if dest.exists() and not force:
        diag_console.print(
            f"[red]Error:[/red] {dest} already exists. Use [bold]--force[/bold] to overwrite."
        )
        raise SystemExit(EXIT_USAGE)

    project_name = name or Path.cwd().name
    content = _INIT_TEMPLATE.format(schema_url=_SCHEMA_URL, project_name=project_name)
    dest.write_text(content, encoding="utf-8")

    console.print(f"[green]✓[/green] Created {dest}")
    console.print(
        f"  Schema: [cyan]{_SCHEMA_URL}[/cyan]\n"
        "  Run [bold]promptgenie config validate[/bold] to check your changes."
    )
