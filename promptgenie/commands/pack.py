import sys

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from promptgenie.core.context_packs import (
    init_pack,
    inject_pack_into_prompt,
    list_packs,
    load_pack,
    render_pack,
)
from promptgenie.core.fileio import FileTooLargeError, safe_read_text, safe_write_text
from promptgenie.renderers.rich import console


@click.group(name="pack")
def pack_group():
    """Manage context packs and registry rule packs."""


@pack_group.command(name="list")
def pack_list():
    """List all available context packs."""
    packs = list_packs()
    if not packs:
        console.print(
            "[dim]No context packs found. Run [bold]promptgenie pack init <id>[/bold] to create one.[/dim]"
        )
        return
    table = Table(title="Context Packs", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Description", style="dim")
    table.add_column("Stack", style="dim")
    for p in packs:
        stack = ", ".join(p["stack"][:3])
        if len(p["stack"]) > 3:
            stack += f" +{len(p['stack']) - 3} more"
        table.add_row(p["id"], p["name"], p["description"], stack)
    console.print(table)


@pack_group.command(name="show")
@click.argument("pack_id")
@click.option(
    "--mode",
    "-m",
    default="standard",
    type=click.Choice(["minimal", "standard", "exhaustive"]),
    help="How much of the pack to render.",
)
def pack_show(pack_id, mode):
    """Show the rendered context block for a pack."""
    try:
        rendered = render_pack(pack_id, mode=mode)
        pack = load_pack(pack_id)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    console.print(
        Panel(
            rendered,
            title=f"Context Pack — {pack.get('name', pack_id)}  [dim]mode: {mode}[/dim]",
            border_style="cyan",
        )
    )


@pack_group.command(name="inject")
@click.argument("prompt_file", type=click.Path(exists=True))
@click.argument("pack_id")
@click.option(
    "--mode", "-m", default="standard", type=click.Choice(["minimal", "standard", "exhaustive"])
)
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(),
    help="Save result to file (defaults to overwrite prompt_file).",
)
@click.option("--force", is_flag=True, help="Overwrite --out file if it already exists.")
def pack_inject(prompt_file, pack_id, mode, out, force):
    """Inject a context pack into an existing prompt file."""
    try:
        prompt_text = safe_read_text(prompt_file)
        result = inject_pack_into_prompt(prompt_text, pack_id, mode=mode)
    except (FileNotFoundError, FileTooLargeError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    dest = out or prompt_file
    # Injecting back into the source file is always an intentional overwrite
    dest_force = force or (dest == prompt_file)
    try:
        safe_write_text(dest, result, force=dest_force)
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    console.print(Panel(result, title=f"Injected — {pack_id} → {dest}", border_style="cyan"))
    console.print(f"[green]Saved to {dest}[/green]")


@pack_group.command(name="search")
@click.argument("query", required=False, default="")
def pack_search(query: str):
    """Search the registry index for available packs."""
    from promptgenie.core.registry import load_index

    entries = load_index()
    if query:
        q = query.lower()
        entries = [
            e
            for e in entries
            if q in e.id.lower() or q in e.name.lower() or q in e.description.lower()
        ]

    if not entries:
        console.print("[dim]No packs found matching your query.[/dim]")
        return

    table = Table(title="Registry Packs", box=box.ROUNDED)
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Version", style="dim")
    table.add_column("Type", style="dim")
    table.add_column("Description", style="dim")
    for e in entries:
        table.add_row(e.id, e.name, e.version, e.type, e.description)
    console.print(table)


@pack_group.command(name="install")
@click.argument("pack_id")
@click.option("--timeout", default=30, type=int, help="Download timeout in seconds.")
@click.option(
    "--allow-unverified",
    is_flag=True,
    default=False,
    help=(
        "Skip SHA-256 checksum requirement.  Use only with a private registry "
        "that does not yet publish checksums.  Not recommended for production."
    ),
)
@click.option("--sha256", "expected_sha256", default=None,
              help="Expected SHA-256 of the local tarball (optional integrity check).")
def pack_install(pack_id: str, timeout: int, allow_unverified: bool, expected_sha256: str | None):
    """Download and install a pack from the registry, or install a local pack.

    PACK_ID can be a registry pack name OR a path to a local .yaml or .tar.gz
    file.  Local paths are installed directly without a network call — ideal for
    air-gapped environments.

    \b
    Examples:
      promptgenie pack install owasp-llm-top10
      promptgenie pack install ./internal-rules.yaml
      promptgenie pack install ./internal-pack.tar.gz --sha256 abc123...
    """
    from pathlib import Path as _Path

    # Detect local path: starts with ./ ../ / or is an existing file
    local_path = _Path(pack_id)
    is_local = pack_id.startswith(("./", "../", "/")) or local_path.exists()

    if is_local:
        from promptgenie.core.registry import install_from_local
        console.print(f"Installing local pack from [bold]{pack_id}[/bold]…")
        try:
            path = install_from_local(
                pack_id, expected_sha256=expected_sha256 if not allow_unverified else None
            )
            console.print(f"[green]✓[/green] Installed to {path}")
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]Install error:[/red] {e}")
            sys.exit(1)
        return

    from promptgenie.core.registry import install_pack, load_index

    entries = load_index()
    matching = [e for e in entries if e.id == pack_id]
    if not matching:
        console.print(f"[red]Error:[/red] Pack {pack_id!r} not found in registry.")
        console.print(
            "[dim]Run [bold]promptgenie pack search[/bold] to list available packs.[/dim]"
        )
        sys.exit(1)

    entry = matching[0]
    console.print(f"Installing [bold]{entry.name}[/bold] [dim]v{entry.version}[/dim]…")
    if allow_unverified:
        console.print(
            "[yellow]Warning:[/yellow] --allow-unverified set — "
            "SHA-256 checksum requirement bypassed."
        )
    try:
        path = install_pack(entry, timeout=timeout, require_checksum=not allow_unverified)
        console.print(f"[green]✓[/green] Installed to {path}")
    except ValueError as e:
        console.print(f"[red]Checksum error:[/red] {e}")
        sys.exit(1)
    except OSError as e:
        console.print(f"[red]Download failed:[/red] {e}")
        sys.exit(1)


@pack_group.command(name="update")
@click.option("--url", default=None, help="Registry index URL (overrides default).")
@click.option("--timeout", default=30, type=int, help="Download timeout in seconds.")
@click.option(
    "--allow-unverified",
    is_flag=True,
    default=False,
    help=(
        "Skip SHA-256 checksum requirement for packs without a checksum in the index.  "
        "Use only with a private registry that does not yet publish checksums."
    ),
)
def pack_update(url: str | None, timeout: int, allow_unverified: bool):
    """Fetch the remote registry and install/update all packs.

    Refuses packs without a SHA-256 checksum by default.  Pass --allow-unverified
    to skip integrity verification (not recommended).
    """
    from promptgenie.core.registry import DEFAULT_REGISTRY_URL, update_registry

    registry_url = url or DEFAULT_REGISTRY_URL
    if allow_unverified:
        console.print(
            "[yellow]Warning:[/yellow] --allow-unverified set — "
            "SHA-256 checksum requirement bypassed."
        )
    console.print(f"[dim]Fetching registry from {registry_url}…[/dim]")
    result = update_registry(
        url=registry_url, timeout=timeout, require_checksum=not allow_unverified
    )

    if result.installed:
        console.print(f"[green]Installed:[/green] {', '.join(result.installed)}")
    if result.updated:
        console.print(f"[blue]Updated:[/blue]   {', '.join(result.updated)}")
    if result.skipped:
        console.print(f"[dim]Up-to-date: {', '.join(result.skipped)}[/dim]")
    if result.errors:
        for err in result.errors:
            console.print(f"[red]Error:[/red] {err}")
        sys.exit(1)

    if not result.installed and not result.updated and not result.errors:
        console.print("[dim]All packs are up to date.[/dim]")


@pack_group.command(name="dirs")
def pack_dirs():
    """Show registry and user rules directories."""
    from promptgenie.core.registry import (
        BUILTIN_PACKS_DIR,
        CACHED_INDEX_PATH,
        USER_PACKS_DIR,
        USER_RULES_DIR,
    )

    table = Table(title="Pack Directories", box=box.ROUNDED, show_header=True)
    table.add_column("Purpose", style="cyan")
    table.add_column("Path")
    table.add_column("Exists", style="dim")

    dirs = [
        ("Built-in packs (shipped)", BUILTIN_PACKS_DIR),
        ("Installed packs (registry)", USER_PACKS_DIR),
        ("Custom rules dir", USER_RULES_DIR),
        ("Cached index", CACHED_INDEX_PATH),
    ]
    for label, path in dirs:
        exists = "✓" if path.exists() else "—"
        table.add_row(label, str(path), exists)
    console.print(table)


@pack_group.command(name="init")
@click.argument("pack_id")
@click.option("--name", default="", help="Human-readable name for the pack.")
@click.option("--description", default="", help="One-line description.")
def pack_init(pack_id, name, description):
    """Create a new blank context pack file."""
    try:
        path = init_pack(pack_id, name=name, description=description)
        console.print(f"[green]Created context pack:[/green] {path}")
        console.print("[dim]Edit the file to fill in your project details, then use:[/dim]")
        console.print(f'  promptgenie generate "your task" --pack {pack_id}')
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# pack diff
# ---------------------------------------------------------------------------

@pack_group.command(name="diff")
@click.argument("pack_a")
@click.argument("pack_b")
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json"], case_sensitive=False),
              default="rich", show_default=True)
def pack_diff(pack_a: str, pack_b: str, output_format: str):
    """Show rule-level diff between two pack versions.

    PACK_A and PACK_B are paths to pack YAML files.

    \b
    Examples:
      promptgenie pack diff security-v1.yaml security-v2.yaml
      promptgenie pack diff old.yaml new.yaml --format json
    """
    from pathlib import Path
    from promptgenie.core.pack_signing import diff_packs

    try:
        diff = diff_packs(pack_a, pack_b)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if output_format == "json":
        import json
        print(json.dumps({
            "old_version": diff.old_version,
            "new_version": diff.new_version,
            "added": diff.added_rules,
            "removed": diff.removed_rules,
            "modified": diff.modified_rules,
        }, indent=2))
        return

    console.print(f"Pack diff: [dim]{pack_a}[/dim] → [dim]{pack_b}[/dim]")
    console.print(f"Version: [dim]{diff.old_version}[/dim] → [bold]{diff.new_version}[/bold]")
    if not diff.has_changes:
        console.print("[green]No rule changes.[/green]")
        return
    for r in diff.added_rules:
        console.print(f"  [green]+[/green] {r}")
    for r in diff.removed_rules:
        console.print(f"  [red]-[/red] {r}")
    for r in diff.modified_rules:
        console.print(f"  [yellow]~[/yellow] {r}")
    console.print(f"\n[dim]{diff.summary()}[/dim]")


# ---------------------------------------------------------------------------
# pack promote
# ---------------------------------------------------------------------------

@pack_group.command(name="promote")
@click.argument("pack_name")
@click.option("--from", "from_env", required=True, help="Source environment (e.g. dev).")
@click.option("--to", "to_env", required=True, help="Target environment (e.g. prod).")
@click.option("--base-dir", default=None, type=click.Path(),
              help="Base directory for pack environment slots.")
def pack_promote(pack_name: str, from_env: str, to_env: str, base_dir):
    """Promote a pack from one environment to another.

    Environment slots: .promptgenie/pack-envs/<env>/<pack>.yaml

    \b
    Examples:
      promptgenie pack promote security-baseline --from dev --to staging
      promptgenie pack promote security-baseline --from staging --to prod
    """
    from pathlib import Path
    from promptgenie.core.pack_signing import promote_pack

    bdir = Path(base_dir) if base_dir else None
    try:
        dest = promote_pack(pack_name, from_env, to_env, base_dir=bdir)
        console.print(
            f"[green]✓[/green] Promoted [bold]{pack_name}[/bold] "
            f"[dim]{from_env}[/dim] → [bold]{to_env}[/bold]: {dest}"
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# pack test
# ---------------------------------------------------------------------------

@pack_group.command(name="test")
@click.argument("pack_file", type=click.Path(exists=True))
@click.argument("test_file", type=click.Path(exists=True))
@click.option("--format", "output_format",
              type=click.Choice(["rich", "json"], case_sensitive=False),
              default="rich", show_default=True)
def pack_test(pack_file: str, test_file: str, output_format: str):
    """Run a pack's unit test suite against its rules.

    \b
    Examples:
      promptgenie pack test security-pack.yaml security-pack.test.yaml
      promptgenie pack test my-pack.yaml tests.yaml --format json
    """
    from promptgenie.core.pack_signing import run_pack_unit_test

    try:
        result = run_pack_unit_test(pack_file, test_file)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    if output_format == "json":
        import json
        print(json.dumps({
            "passed": result.passed,
            "total": result.total,
            "pass_count": result.pass_count,
            "fail_count": result.fail_count,
            "cases": result.cases,
        }, indent=2))
        sys.exit(0 if result.passed else 1)

    status = "PASSED" if result.passed else "FAILED"
    color = "green" if result.passed else "red"
    console.print(
        f"[bold {color}]{status}[/bold {color}]  "
        f"{result.pass_count}/{result.total} cases"
    )
    for c in result.cases:
        icon = "[green]✓[/green]" if c["passed"] else "[red]✗[/red]"
        console.print(f"  {icon} {c['name']}")
        if not c["passed"]:
            console.print(
                f"    Expected: {c['expected_rules']}  "
                f"Found: {c['found_rules']}"
            )
    sys.exit(0 if result.passed else 1)


# ---------------------------------------------------------------------------
# pack verify (signature)
# ---------------------------------------------------------------------------

@pack_group.command(name="verify")
@click.argument("pack_file", type=click.Path(exists=True))
@click.option("--pubkey", required=True, help="Path to public key file.")
@click.option("--method",
              type=click.Choice(["minisign", "cosign"], case_sensitive=False),
              default="minisign", show_default=True)
def pack_verify(pack_file: str, pubkey: str, method: str):
    """Verify a pack's cryptographic signature.

    Requires the companion .minisig or .cosig file adjacent to the pack.

    \b
    Examples:
      promptgenie pack verify security.yaml --pubkey trusted.pub
      promptgenie pack verify security.yaml --pubkey trusted.pub --method cosign
    """
    from promptgenie.core.pack_signing import verify_pack_signature

    try:
        ok = verify_pack_signature(pack_file, pubkey, method=method)
        if ok:
            console.print(f"[green]✓[/green] Signature valid ({method}): {pack_file}")
        else:
            console.print(f"[red]✗[/red] Signature INVALID ({method}): {pack_file}")
            sys.exit(1)
    except (FileNotFoundError, RuntimeError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
