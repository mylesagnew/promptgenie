"""auth.py — ``promptgenie auth`` command group.

Commands
--------
  promptgenie auth login <provider>   store an API key in the system keyring
  promptgenie auth logout <provider>  remove a stored API key
  promptgenie auth status             show credential status for all providers
"""

from __future__ import annotations

import os

import click

from promptgenie.core.credentials import (
    delete_credential,
    get_credential,
    is_keyring_available,
    list_stored_credentials,
    store_credential,
    store_credential_ref,
)
from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE
from promptgenie.core.providers import load_providers_config
from promptgenie.renderers.rich import console, diag_console

_EXTERNAL_SOURCES = {"1password", "aws-ssm", "gcp-secret", "azure-keyvault"}


@click.group("auth", help="Manage API credentials for AI providers.")
def auth_group() -> None:
    pass


# ---------------------------------------------------------------------------
# auth login
# ---------------------------------------------------------------------------


@auth_group.command("login")
@click.argument("provider")
@click.option("--key", default=None, envvar="PG_API_KEY",
              help="API key value. If omitted, prompted interactively.")
@click.option("--env-var", default=None,
              help="Read key from this environment variable instead of prompting.")
@click.option(
    "--source",
    type=click.Choice(["keyring", "env", "1password", "aws-ssm", "gcp-secret", "azure-keyvault"]),
    default="keyring", show_default=True,
    help=(
        "Where to read/store the credential. "
        "'keyring' stores the raw key in the system keyring (default). "
        "'env' reads the key from --env-var and stores it in the keyring. "
        "External sources (1password, aws-ssm, gcp-secret, azure-keyvault) store a "
        "ref: pointer in providers.yaml and resolve it at runtime."
    ),
)
@click.option("--ref", "ref_path", default=None,
              help=(
                  "Path in the external secret manager, e.g. "
                  "'MyVault/anthropic/api_key' for 1password, "
                  "'/promptgenie/anthropic/key' for aws-ssm."
              ))
def auth_login_cmd(
    provider: str,
    key: str | None,
    env_var: str | None,
    source: str,
    ref_path: str | None,
) -> None:
    """Store an API key for PROVIDER in the system credential store.

    By default stores in the system keyring (macOS Keychain, Windows Credential
    Manager, SecretService). Use --source to delegate to an external secret
    manager — only a ref: pointer is written to providers.yaml, never the raw key.

    \b
    Examples:
      promptgenie auth login anthropic
      promptgenie auth login openai --key sk-...
      promptgenie auth login anthropic --source aws-ssm --ref /promptgenie/anthropic/key
      promptgenie auth login anthropic --source 1password --ref MyVault/anthropic/api_key
      promptgenie auth login anthropic --source gcp-secret --ref my-project/anthropic-key
      promptgenie auth login anthropic --source azure-keyvault --ref my-vault/anthropic-key
    """
    # ── External secret manager path ─────────────────────────────────────────
    if source in _EXTERNAL_SOURCES:
        if not ref_path:
            ref_path = click.prompt(
                f"Secret path in {source} for provider {provider!r}"
            )
        scheme_map = {
            "1password": "1password",
            "aws-ssm": "aws-ssm",
            "gcp-secret": "gcp-secret",
            "azure-keyvault": "azure-kv",
        }
        scheme = scheme_map[source]
        ref = f"ref:{scheme}:{ref_path}"
        try:
            store_credential_ref(provider, ref)
        except Exception as exc:
            diag_console.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(EXIT_USAGE)
        console.print(
            f"[green]✓[/green] Credential reference for [bold]{provider}[/bold] stored: "
            f"[dim]{ref}[/dim]"
        )
        console.print(
            f"[dim]The key will be resolved from {source} at runtime.[/dim]"
        )
        return

    # ── Keyring / env path ───────────────────────────────────────────────────
    if not is_keyring_available():
        diag_console.print(
            "[yellow]⚠[/yellow] System keyring not available.\n"
            "Install it with: [bold]pip install 'promptgenie[secrets]'[/bold]\n"
            "The key will be stored in providers.yaml instead (less secure)."
        )

    # Resolve key value
    if env_var or source == "env":
        env_name = env_var or click.prompt(f"Environment variable name for {provider!r}")
        key = os.environ.get(env_name)
        if not key:
            diag_console.print(
                f"[red]Error:[/red] Environment variable {env_name!r} is not set."
            )
            raise SystemExit(EXIT_USAGE)
    elif not key:
        key = click.prompt(f"API key for {provider!r}", hide_input=True)

    if not key:
        diag_console.print("[red]Error:[/red] No API key provided.")
        raise SystemExit(EXIT_USAGE)

    try:
        store_credential(provider, key)
        console.print(
            f"[green]✓[/green] API key for [bold]{provider}[/bold] stored in system keyring."
        )
    except ImportError:
        # Fallback: save to providers.yaml api_key field
        from promptgenie.core.providers import load_providers_config, save_providers_config
        providers = load_providers_config()
        if provider not in providers:
            diag_console.print(
                f"[yellow]⚠[/yellow] Provider '{provider}' not configured. "
                f"Add it first with: promptgenie provider add {provider}"
            )
            raise SystemExit(EXIT_USAGE)
        providers[provider].api_key = key
        save_providers_config(providers)
        console.print(
            f"[yellow]⚠[/yellow] Keyring unavailable. Key saved to providers.yaml. "
            "Install keyring for secure storage: pip install 'promptgenie[secrets]'"
        )


# ---------------------------------------------------------------------------
# auth logout
# ---------------------------------------------------------------------------


@auth_group.command("logout")
@click.argument("provider")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def auth_logout_cmd(provider: str, yes: bool) -> None:
    """Remove stored credentials for PROVIDER.

    Example:
      promptgenie auth logout anthropic
    """
    if not yes:
        click.confirm(f"Remove stored credentials for '{provider}'?", abort=True)

    deleted = delete_credential(provider)
    if deleted:
        console.print(f"[green]✓[/green] Credentials for [bold]{provider}[/bold] removed.")
    else:
        diag_console.print(
            f"[yellow]No stored credentials found for '{provider}'.[/yellow]"
        )


# ---------------------------------------------------------------------------
# auth status
# ---------------------------------------------------------------------------


@auth_group.command("status")
def auth_status_cmd() -> None:
    """Show credential status for all configured providers.

    Checks environment variables, keyring, and config file for each provider.

    Example:
      promptgenie auth status
    """
    providers = load_providers_config()
    keyring_ok = is_keyring_available()

    if not providers:
        console.print("[dim]No providers configured.[/dim]")
        raise SystemExit(EXIT_OK)

    from rich.table import Table
    table = Table(title="Credential Status", show_header=True, header_style="bold")
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Type", width=14)
    table.add_column("Env Var", no_wrap=True)
    table.add_column("Env Set", width=8)
    table.add_column("Keyring", width=8)
    table.add_column("Status")

    all_ok = True
    for name, cfg in providers.items():
        env_var = cfg.api_key_env or "—"
        env_set = bool(os.environ.get(cfg.api_key_env, "")) if cfg.api_key_env else False

        keyring_has = False
        if keyring_ok:
            try:
                import keyring  # type: ignore[import-untyped]
                keyring_has = bool(keyring.get_password("promptgenie", name))
            except Exception:
                pass

        is_local = cfg.local or cfg.type == "openai_compat" and not cfg.api_key_env
        if is_local and not cfg.api_key_env:
            status = "[dim]local — no key needed[/dim]"
            env_set_str = "—"
            keyring_str = "—"
        elif env_set:
            status = "[green]✓ Ready[/green]"
            env_set_str = "[green]✓[/green]"
            keyring_str = "[green]✓[/green]" if keyring_has else "—"
        elif keyring_has:
            status = "[green]✓ Ready (keyring)[/green]"
            env_set_str = "—"
            keyring_str = "[green]✓[/green]"
        elif cfg.api_key:
            status = "[yellow]⚠ Key in config (insecure)[/yellow]"
            env_set_str = "—"
            keyring_str = "—"
        else:
            status = "[red]✗ No credentials[/red]"
            env_set_str = "—"
            keyring_str = "—"
            all_ok = False

        table.add_row(name, cfg.type, env_var, env_set_str, keyring_str, status)

    console.print(table)

    if not keyring_ok:
        console.print(
            "\n[dim]Keyring not available. Install with: "
            "pip install 'promptgenie[secrets]'[/dim]"
        )

    if not all_ok:
        raise SystemExit(EXIT_FAILURE)
