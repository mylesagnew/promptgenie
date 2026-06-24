"""provider.py — ``promptgenie provider`` command group.

Commands
--------
  promptgenie provider list            list configured providers
  promptgenie provider add <name>      add or update a provider
  promptgenie provider remove <name>   remove a provider
  promptgenie provider doctor <name>   test provider reachability
  promptgenie provider show <name>     show provider config
"""

from __future__ import annotations

import asyncio
import json

import click
import yaml

from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.core.providers import (
    _PROVIDERS_FILE,
    add_provider,
    load_providers_config,
    probe_provider,
    save_providers_config,
)
from promptgenie.renderers.rich import console, diag_console, is_structured_mode


@click.group("provider", help="Manage AI provider configurations.")
def provider_group() -> None:
    pass


# ---------------------------------------------------------------------------
# provider list
# ---------------------------------------------------------------------------


@provider_group.command("list")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json", "yaml"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def provider_list_cmd(output_format: str) -> None:
    """List all configured providers.

    Example:

      promptgenie provider list

      promptgenie provider list --format json | jq '.[].name'
    """
    providers = load_providers_config()

    if is_structured_mode(output_format):
        out = [
            {
                "name": p.name,
                "type": p.type,
                "base_url": p.base_url,
                "default_model": p.default_model,
                "local": p.local,
                "api_key_env": p.api_key_env,
            }
            for p in providers.values()
        ]
        if output_format == "yaml":
            console.print(yaml.dump({"providers": out}, default_flow_style=False))
        else:
            console.print(json.dumps({"schema_version": "1.0", "providers": out}, indent=2))
        return

    if not providers:
        console.print(
            "[dim]No providers configured. Run 'promptgenie provider add' to add one.[/dim]"
        )
        return

    from rich.table import Table

    table = Table(title="Configured Providers", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Model")
    table.add_column("Endpoint/Key")
    table.add_column("Local")

    for p in providers.values():
        endpoint = p.base_url or p.api_key_env or "—"
        table.add_row(
            p.name,
            p.type,
            p.default_model or "—",
            endpoint,
            "✓" if p.local else "—",
        )
    console.print(table)
    console.print(f"[dim]Config: {_PROVIDERS_FILE}[/dim]")


# ---------------------------------------------------------------------------
# provider add
# ---------------------------------------------------------------------------


@provider_group.command("add")
@click.argument("name")
@click.option(
    "--type",
    "provider_type",
    type=click.Choice(["anthropic", "openai_compat"], case_sensitive=False),
    default="openai_compat",
    show_default=True,
    help="Provider type.",
)
@click.option("--base-url", default="", help="API base URL (OpenAI-compat providers).")
@click.option("--api-key-env", default="", help="Environment variable name that holds the API key.")
@click.option("--model", "default_model", default="", help="Default model name.")
@click.option(
    "--local", is_flag=True, help="Mark as a local provider (no API key required by default)."
)
def provider_add_cmd(
    name: str,
    provider_type: str,
    base_url: str,
    api_key_env: str,
    default_model: str,
    local: bool,
) -> None:
    """Add or update a provider configuration.

    \b
    Examples:
      promptgenie provider add ollama \\
        --base-url http://localhost:11434/v1 \\
        --model llama3 --local

      promptgenie provider add my-openai \\
        --type openai_compat \\
        --base-url https://api.openai.com/v1 \\
        --api-key-env OPENAI_API_KEY \\
        --model gpt-4o

      promptgenie provider add lm-studio \\
        --base-url http://localhost:1234/v1 \\
        --model local-model --local
    """
    add_provider(
        name,
        provider_type=provider_type,
        base_url=base_url,
        api_key_env=api_key_env,
        default_model=default_model,
        local=local,
    )
    console.print(f"[green]✓[/green] Provider [bold]{name}[/bold] saved to {_PROVIDERS_FILE}")
    if base_url:
        console.print(f"  Base URL: {base_url}")
    if default_model:
        console.print(f"  Default model: {default_model}")
    console.print(f"  Run [bold]promptgenie provider doctor {name}[/bold] to test reachability.")


# ---------------------------------------------------------------------------
# provider remove
# ---------------------------------------------------------------------------


@provider_group.command("remove")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def provider_remove_cmd(name: str, yes: bool) -> None:
    """Remove a provider configuration.

    Example:

      promptgenie provider remove my-old-provider --yes
    """
    providers = load_providers_config()
    if name not in providers:
        diag_console.print(f"[red]Provider '{name}' not found.[/red]")
        raise SystemExit(EXIT_USAGE)

    if not yes:
        click.confirm(f"Remove provider '{name}'?", abort=True)

    del providers[name]
    save_providers_config(providers)
    console.print(f"[green]✓[/green] Provider '{name}' removed.")


# ---------------------------------------------------------------------------
# provider show
# ---------------------------------------------------------------------------


@provider_group.command("show")
@click.argument("name")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json", "yaml"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def provider_show_cmd(name: str, output_format: str) -> None:
    """Show details for a specific provider.

    Example:

      promptgenie provider show ollama

      promptgenie provider show anthropic --format json
    """
    providers = load_providers_config()
    if name not in providers:
        diag_console.print(f"[red]Provider '{name}' not found.[/red]")
        raise SystemExit(EXIT_USAGE)

    p = providers[name]
    data = {
        "name": p.name,
        "type": p.type,
        "base_url": p.base_url,
        "default_model": p.default_model,
        "local": p.local,
        "api_key_env": p.api_key_env,
        "capabilities": {
            "streaming": p.capabilities.streaming,
            "structured_output": p.capabilities.structured_output,
            "max_context_tokens": p.capabilities.max_context_tokens,
            "supports_tools": p.capabilities.supports_tools,
            "local": p.capabilities.local,
        },
    }

    if is_structured_mode(output_format):
        if output_format == "yaml":
            console.print(yaml.dump(data, default_flow_style=False))
        else:
            console.print(json.dumps(data, indent=2))
        return

    console.print(f"[bold cyan]{p.name}[/bold cyan]")
    for k, v in data.items():
        if k == "capabilities" and isinstance(v, dict):
            console.print("  capabilities:")
            for ck, cv in v.items():
                console.print(f"    {ck}: {cv}")
        elif v:
            console.print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# provider doctor
# ---------------------------------------------------------------------------


@provider_group.command("doctor")
@click.argument("name")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "json"], case_sensitive=False),
    default="rich",
)
def provider_doctor_cmd(name: str, output_format: str) -> None:
    """Test reachability and configuration of a provider.

    \b
    Examples:
      promptgenie provider doctor ollama
      promptgenie provider doctor anthropic
      promptgenie provider doctor my-openai --format json
    """
    ok, message = asyncio.run(probe_provider(name))
    status = "ok" if ok else "error"

    providers = load_providers_config()
    cfg = providers.get(name)
    cap = cfg.capabilities if cfg else None

    if is_structured_mode(output_format):
        cap_dict = {}
        if cap:
            cap_dict = {
                "streaming": cap.streaming,
                "structured_output": cap.structured_output,
                "max_context_tokens": cap.max_context_tokens,
                "local": cap.local,
                "supports_tools": cap.supports_tools,
            }
        console.print(
            json.dumps(
                {
                    "provider": name,
                    "status": status,
                    "message": message,
                    "capabilities": cap_dict,
                    "schema_version": "1.0",
                },
                indent=2,
            )
        )
    else:
        icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f"{icon} [bold]{name}[/bold]: {message}")
        if cap:
            from rich.table import Table
            table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
            table.add_column("Capability")
            table.add_column("Value")
            table.add_row("streaming",        "[green]yes[/green]" if cap.streaming else "no")
            table.add_row("structured_output","[green]yes[/green]" if cap.structured_output else "no")
            table.add_row("supports_tools",   "[green]yes[/green]" if cap.supports_tools else "no")
            table.add_row("local",            "[green]yes[/green]" if cap.local else "no")
            table.add_row("max_context_tokens", f"{cap.max_context_tokens:,}")
            console.print(table)

    raise SystemExit(EXIT_OK if ok else EXIT_FAILURE)
