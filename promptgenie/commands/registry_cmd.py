"""registry_cmd.py — ``promptgenie registry`` command group.

A versioned, signed, content-addressable store for prompt artifacts. Phase A is
local-first: a filesystem store under ``~/.local/share/promptgenie/registry``
(override with ``--store-path`` or ``PROMPTGENIE_REGISTRY_PATH``).

Examples
--------
  promptgenie registry push prompts/auth.promptgenie.yaml --tag v1.2
  promptgenie registry push prompt.yaml --tag v1 --sign --key ~/.minisign/pg.key
  promptgenie registry pull org/auth-review:v1.2 --out ./vendored
  promptgenie registry pull org/auth-review:latest --require-signed --pubkey pg.pub
  promptgenie registry list --format json
  promptgenie registry show org/auth-review:v1.2
  promptgenie registry prune --dry-run
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
import yaml

from promptgenie.core.artifact import build_artifact, materialise, push_bundle
from promptgenie.core.errors import EXIT_FAILURE, EXIT_OK, EXIT_USAGE, PromptGenieError
from promptgenie.core.registry_backend import resolve_push_target, resolve_ref_target
from promptgenie.core.registry_signing import sign_manifest, verify_manifest
from promptgenie.core.registry_store import (
    LocalRegistryStore,
    Reference,
    RegistryError,
)
from promptgenie.renderers.rich import diag_console, is_structured_mode

_SPEC_SUFFIXES = {".yaml", ".yml", ".json"}


def _store(store_path: str | None) -> LocalRegistryStore:
    path = store_path or os.environ.get("PROMPTGENIE_REGISTRY_PATH")
    return LocalRegistryStore(path)


def _audit(**kwargs: object) -> None:
    """Best-effort audit write — never let provenance logging break a command."""
    try:
        from promptgenie.core.audit import write_audit_event

        write_audit_event(**kwargs)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover - audit DB unavailable
        pass


def _derive_repository(source: Path) -> str:
    """Derive a repository name when --name is omitted (spec name / filename)."""
    if source.suffix.lower() in _SPEC_SUFFIXES:
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict) and raw.get("name"):
                return str(raw["name"]).strip().lower()
        except Exception:
            pass
    stem = source.name
    for suffix in (".promptgenie.yaml", ".promptgenie.yml"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)].lower()
    return source.stem.lower()


@click.group(name="registry")
def registry_group() -> None:
    """Versioned, signed, content-addressable store for prompt artifacts."""


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


@registry_group.command("push")
@click.argument("source", type=click.Path(exists=True, dir_okay=False))
@click.option("--name", "-n", default=None, help="Repository name (default: derived from the spec).")
@click.option("--tag", "-t", default="latest", show_default=True, help="Tag to assign.")
@click.option("--description", "-d", default="", help="Human description stored in the artifact.")
@click.option("--annotate", "-a", multiple=True, metavar="K=V", help="Extra manifest annotation (repeatable).")
@click.option("--sign", is_flag=True, help="Sign the manifest after push.")
@click.option("--key", "secret_key", default=None, help="Secret key for --sign.")
@click.option("--method", type=click.Choice(["minisign", "cosign"]), default="minisign", show_default=True)
@click.option("--remote", default=None, help="Push to a remote OCI registry (host[/namespace]).")
@click.option("--insecure", is_flag=True, help="Allow http:// and skip TLS verification (remote only).")
@click.option("--store-path", default=None, type=click.Path(), help="Local registry store root.")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def registry_push(
    source: str,
    name: str | None,
    tag: str,
    description: str,
    annotate: tuple[str, ...],
    sign: bool,
    secret_key: str | None,
    method: str,
    remote: str | None,
    insecure: bool,
    store_path: str | None,
    output_format: str,
) -> None:
    """Bundle a spec/prompt and its inputs into the registry under REPO:TAG."""
    src = Path(source)
    repository = (name or _derive_repository(src)).strip().lower()

    annotations: dict[str, str] = {}
    for item in annotate:
        if "=" not in item:
            diag_console.print(f"[red]Error:[/red] --annotate must be K=V, got {item!r}")
            raise SystemExit(EXIT_USAGE)
        k, _, v = item.partition("=")
        annotations[k.strip()] = v.strip()

    try:
        Reference.parse(f"{repository}:{tag}")  # validates repo + tag
        store, repository = resolve_push_target(
            remote, repository, store_path=store_path, insecure=insecure
        )
        bundle = build_artifact(src, name=repository, tag=tag, description=description, annotate=annotations)
        digest = push_bundle(store, bundle, repository, tag)
        if sign:
            if not secret_key:
                diag_console.print("[red]Error:[/red] --sign requires --key.")
                raise SystemExit(EXIT_USAGE)
            sign_manifest(store, digest, secret_key, method=method)
    except (RegistryError, PromptGenieError) as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc
    except RuntimeError as exc:  # signing tool missing/failed
        diag_console.print(f"[red]Signing failed:[/red] {exc}")
        raise SystemExit(EXIT_FAILURE) from exc

    manifest = bundle.manifest()
    total = manifest.config.size + sum(layer.size for layer in manifest.layers)
    _audit(
        command="registry push",
        spec_name=repository,
        status="ok",
        extra={"ref": f"{repository}:{tag}", "digest": digest, "signed": sign},
    )

    if is_structured_mode(output_format):
        _emit_json(
            {
                "schema_version": "1.0",
                "repository": repository,
                "tag": tag,
                "digest": digest,
                "signed": sign,
                "layers": [
                    {"kind": layer.annotations.get("org.promptgenie.kind", ""),
                     "path": layer.annotations.get("org.promptgenie.path", ""),
                     "digest": layer.digest, "size": layer.size}
                    for layer in manifest.layers
                ],
                "total_bytes": total,
            }
        )
    else:
        diag_console.print(
            f"[green]✓[/green] pushed [bold]{repository}:{tag}[/bold]  "
            f"{len(manifest.layers)} layer(s), {total} bytes{'  [cyan](signed)[/cyan]' if sign else ''}"
        )
        diag_console.print(f"  digest: [dim]{digest}[/dim]")
    raise SystemExit(EXIT_OK)


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


@registry_group.command("pull")
@click.argument("ref")
@click.option("--out", "-o", default=None, type=click.Path(), help="Output directory (default: ./<name>).")
@click.option("--require-signed", is_flag=True, help="Fail unless a valid signature is present.")
@click.option("--pubkey", default=None, help="Public key for signature verification.")
@click.option("--method", type=click.Choice(["minisign", "cosign"]), default=None)
@click.option("--remote", default=None, help="Pull from a remote OCI registry (host[/namespace]).")
@click.option("--insecure", is_flag=True, help="Allow http:// and skip TLS verification (remote only).")
@click.option("--store-path", default=None, type=click.Path())
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def registry_pull(
    ref: str,
    out: str | None,
    require_signed: bool,
    pubkey: str | None,
    method: str | None,
    remote: str | None,
    insecure: bool,
    store_path: str | None,
    output_format: str,
) -> None:
    """Resolve REF, verify digests (and signature if asked), materialise files."""
    try:
        reference = Reference.parse(ref)
        store, reference = resolve_ref_target(
            reference, remote, store_path=store_path, insecure=insecure
        )
        digest = store.resolve_ref(reference)

        if require_signed or pubkey:
            if not pubkey:
                diag_console.print("[red]Error:[/red] --require-signed needs --pubkey.")
                raise SystemExit(EXIT_USAGE)
            if not verify_manifest(store, digest, pubkey, method=method):
                diag_console.print(f"[red]✗ signature verification failed[/red] for {reference}")
                raise SystemExit(EXIT_FAILURE)

        manifest = store.get_manifest(digest)  # verifies manifest digest
        out_dir = Path(out) if out else Path.cwd() / reference.name
        written = materialise(store, manifest, out_dir)  # verifies each layer digest
    except RegistryError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    _audit(
        command="registry pull",
        spec_name=reference.repository,
        status="ok",
        extra={"ref": str(reference), "digest": digest, "verified": bool(pubkey)},
    )

    if is_structured_mode(output_format):
        _emit_json(
            {
                "schema_version": "1.0",
                "repository": reference.repository,
                "digest": digest,
                "verified": bool(pubkey),
                "out_dir": str(out_dir),
                "files": [str(p) for p in written],
            }
        )
    else:
        verified = "  [cyan](signature verified)[/cyan]" if pubkey else ""
        diag_console.print(
            f"[green]✓[/green] pulled [bold]{reference}[/bold] → {out_dir}  "
            f"{len(written)} file(s){verified}"
        )
        for p in written:
            diag_console.print(f"  [dim]{p}[/dim]")
    raise SystemExit(EXIT_OK)


# ---------------------------------------------------------------------------
# list / tags / show / verify / rm / prune / search
# ---------------------------------------------------------------------------


@registry_group.command("list")
@click.option("--name", default=None, help="Restrict to a single repository.")
@click.option("--store-path", default=None, type=click.Path())
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def registry_list(name: str | None, store_path: str | None, output_format: str) -> None:
    """List repositories and tags in the store."""
    store = _store(store_path)
    tags = store.list_tags(name) if name else store.all_tags()
    if is_structured_mode(output_format):
        _emit_json(
            {
                "schema_version": "1.0",
                "artifacts": [
                    {"repository": t.repository, "tag": t.tag, "digest": t.digest,
                     "signed": store.has_signature(t.digest)}
                    for t in tags
                ],
            }
        )
        raise SystemExit(EXIT_OK)
    if not tags:
        diag_console.print("[dim]No artifacts in the registry.[/dim]")
        raise SystemExit(EXIT_OK)
    diag_console.print("[bold]Registry[/bold]")
    for t in tags:
        sig = " [cyan]✎[/cyan]" if store.has_signature(t.digest) else ""
        diag_console.print(f"  [bold]{t.repository}[/bold]:{t.tag}{sig}  [dim]{t.digest[:19]}…[/dim]")
    raise SystemExit(EXIT_OK)


@registry_group.command("tags")
@click.argument("repository")
@click.option("--remote", default=None, help="Query a remote OCI registry (host[/namespace]).")
@click.option("--insecure", is_flag=True, help="Allow http:// and skip TLS verification (remote only).")
@click.option("--store-path", default=None, type=click.Path())
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def registry_tags(
    repository: str, remote: str | None, insecure: bool, store_path: str | None, output_format: str
) -> None:
    """List the tags of a repository."""
    try:
        store, ref = resolve_ref_target(
            Reference.parse(repository if ":" in repository or "/" in repository else f"{repository}:latest"),
            remote,
            store_path=store_path,
            insecure=insecure,
        )
    except RegistryError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc
    repository = ref.repository
    tags = store.list_tags(repository)
    if is_structured_mode(output_format):
        _emit_json({"schema_version": "1.0", "repository": repository,
                    "tags": [{"tag": t.tag, "digest": t.digest} for t in tags]})
        raise SystemExit(EXIT_OK)
    if not tags:
        diag_console.print(f"[dim]No tags for {repository}.[/dim]")
        raise SystemExit(EXIT_OK)
    for t in tags:
        diag_console.print(f"  {t.tag}  [dim]{t.digest[:19]}…[/dim]")
    raise SystemExit(EXIT_OK)


@registry_group.command("show")
@click.argument("ref")
@click.option("--remote", default=None, help="Query a remote OCI registry (host[/namespace]).")
@click.option("--insecure", is_flag=True, help="Allow http:// and skip TLS verification (remote only).")
@click.option("--store-path", default=None, type=click.Path())
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def registry_show(
    ref: str, remote: str | None, insecure: bool, store_path: str | None, output_format: str
) -> None:
    """Show a manifest, its layers, and provenance metadata."""
    try:
        reference = Reference.parse(ref)
        store, reference = resolve_ref_target(reference, remote, store_path=store_path, insecure=insecure)
        digest = store.resolve_ref(reference)
        manifest = store.get_manifest(digest)
        config = json.loads(store.get_blob(manifest.config.digest))
    except (RegistryError, json.JSONDecodeError) as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc

    if is_structured_mode(output_format):
        _emit_json(
            {
                "schema_version": "1.0",
                "reference": str(reference),
                "digest": digest,
                "signed": store.has_signature(digest),
                "config": config,
                "manifest": manifest.to_dict(),
            }
        )
        raise SystemExit(EXIT_OK)
    diag_console.print(f"[bold]{reference}[/bold]")
    diag_console.print(f"  digest: [dim]{digest}[/dim]")
    diag_console.print(f"  signed: {'yes' if store.has_signature(digest) else 'no'}")
    for key in ("provider", "model", "target", "classification"):
        if config.get(key):
            diag_console.print(f"  {key}: {config[key]}")
    if config.get("dynamic_context"):
        diag_console.print(f"  dynamic context: {', '.join(config['dynamic_context'])}")
    diag_console.print("  layers:")
    for layer in manifest.layers:
        kind = layer.annotations.get("org.promptgenie.kind", "?")
        path = layer.annotations.get("org.promptgenie.path", "")
        diag_console.print(f"    • [bold]{kind}[/bold] {path}  [dim]{layer.size} B  {layer.digest[:19]}…[/dim]")
    raise SystemExit(EXIT_OK)


@registry_group.command("verify")
@click.argument("ref")
@click.option("--pubkey", required=True, help="Public key to verify against.")
@click.option("--method", type=click.Choice(["minisign", "cosign"]), default=None)
@click.option("--remote", default=None, help="Query a remote OCI registry (host[/namespace]).")
@click.option("--insecure", is_flag=True, help="Allow http:// and skip TLS verification (remote only).")
@click.option("--store-path", default=None, type=click.Path())
def registry_verify(
    ref: str, pubkey: str, method: str | None, remote: str | None, insecure: bool, store_path: str | None
) -> None:
    """Verify an artifact's signature and re-check every layer digest."""
    try:
        reference = Reference.parse(ref)
        store, reference = resolve_ref_target(reference, remote, store_path=store_path, insecure=insecure)
        digest = store.resolve_ref(reference)
        sig_ok = verify_manifest(store, digest, pubkey, method=method)
        manifest = store.get_manifest(digest)  # verifies manifest digest
        for layer in manifest.layers:
            store.get_blob(layer.digest)  # verifies each layer digest (raises on mismatch)
        store.get_blob(manifest.config.digest)
    except RegistryError as exc:
        diag_console.print(f"[red]✗[/red] integrity check failed: {exc}")
        raise SystemExit(EXIT_FAILURE) from exc

    if not sig_ok:
        diag_console.print(f"[red]✗ signature invalid or missing[/red] for {reference}")
        raise SystemExit(EXIT_FAILURE)
    diag_console.print(f"[green]✓[/green] {reference}: signature valid, all {len(manifest.layers)} layer digest(s) verified.")
    raise SystemExit(EXIT_OK)


@registry_group.command("rm")
@click.argument("ref")
@click.option("--store-path", default=None, type=click.Path())
def registry_rm(ref: str, store_path: str | None) -> None:
    """Remove a tag (run 'prune' to reclaim unreferenced blobs)."""
    try:
        reference = Reference.parse(ref)
        if not reference.tag:
            diag_console.print("[red]Error:[/red] rm requires a tag (repository:tag).")
            raise SystemExit(EXIT_USAGE)
        store = _store(store_path)
        store.remove_tag(reference.repository, reference.tag)
    except RegistryError as exc:
        diag_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(EXIT_USAGE) from exc
    diag_console.print(f"[green]✓[/green] removed {reference.repository}:{reference.tag}")
    raise SystemExit(EXIT_OK)


@registry_group.command("prune")
@click.option("--dry-run", is_flag=True, help="Report what would be removed without deleting.")
@click.option("--store-path", default=None, type=click.Path())
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def registry_prune(dry_run: bool, store_path: str | None, output_format: str) -> None:
    """Garbage-collect blobs/manifests no longer referenced by any tag."""
    store = _store(store_path)
    removed = store.gc(dry_run=dry_run)
    if is_structured_mode(output_format):
        _emit_json({"schema_version": "1.0", "dry_run": dry_run,
                    "removed": removed, "removed_count": len(removed)})
        raise SystemExit(EXIT_OK)
    verb = "would remove" if dry_run else "removed"
    diag_console.print(f"[green]✓[/green] {verb} {len(removed)} unreferenced object(s).")
    raise SystemExit(EXIT_OK)


@registry_group.command("search")
@click.argument("query")
@click.option("--store-path", default=None, type=click.Path())
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def registry_search(query: str, store_path: str | None, output_format: str) -> None:
    """Search artifacts by repository name or manifest annotations."""
    store = _store(store_path)
    q = query.lower()
    hits = []
    for t in store.all_tags():
        haystack = [t.repository, t.tag]
        try:
            manifest = store.get_manifest(t.digest)
            haystack.extend(str(v) for v in manifest.annotations.values())
        except RegistryError:
            pass
        if any(q in h.lower() for h in haystack):
            hits.append(t)

    if is_structured_mode(output_format):
        _emit_json({"schema_version": "1.0", "query": query,
                    "results": [{"repository": t.repository, "tag": t.tag, "digest": t.digest} for t in hits]})
        raise SystemExit(EXIT_OK)
    if not hits:
        diag_console.print(f"[dim]No artifacts match {query!r}.[/dim]")
        raise SystemExit(EXIT_OK)
    for t in hits:
        diag_console.print(f"  [bold]{t.repository}[/bold]:{t.tag}  [dim]{t.digest[:19]}…[/dim]")
    raise SystemExit(EXIT_OK)


@registry_group.command("login")
@click.argument("remote")
@click.option("--token", default=None, help="Bearer token (prefer --token-stdin to avoid shell history).")
@click.option("--token-stdin", "token_stdin", is_flag=True, help="Read the token from stdin.")
def registry_login(remote: str, token: str | None, token_stdin: bool) -> None:
    """Store a bearer token for a remote registry HOST."""
    from promptgenie.core.registry_auth import normalize_host, store_token

    if token_stdin:
        token = sys.stdin.readline().strip()
    if not token:
        diag_console.print("[red]Error:[/red] provide a token via --token or --token-stdin.")
        raise SystemExit(EXIT_USAGE)
    host = normalize_host(remote)
    where = store_token(host, token)
    _audit(command="registry login", extra={"host": host, "stored": where})
    diag_console.print(f"[green]✓[/green] stored token for [bold]{host}[/bold] ({where}).")
    raise SystemExit(EXIT_OK)


@registry_group.command("logout")
@click.argument("remote")
def registry_logout(remote: str) -> None:
    """Remove a stored token for a remote registry HOST."""
    from promptgenie.core.registry_auth import delete_token, normalize_host

    host = normalize_host(remote)
    removed = delete_token(host)
    if removed:
        diag_console.print(f"[green]✓[/green] removed token for [bold]{host}[/bold].")
    else:
        diag_console.print(f"[dim]No stored token for {host}.[/dim]")
    raise SystemExit(EXIT_OK)


def _emit_json(data: dict) -> None:
    sys.stdout.write(json.dumps(data, indent=2) + "\n")
    sys.stdout.flush()


# Re-export for symmetry with other command modules.
__all__ = ["registry_group"]
