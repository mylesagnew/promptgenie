"""registry_backend.py — choose a local or remote registry store for a request.

Both :class:`~promptgenie.core.registry_store.LocalRegistryStore` and the
repository-bound :class:`~promptgenie.core.registry_remote.RemoteRegistryStore`
expose the same surface, captured by the :class:`RegistryStore` Protocol — so the
``registry`` commands, ``push_bundle``, ``materialise``, and ``registry_signing``
are all backend-agnostic.

``resolve_*`` map a ``--remote`` value (or a reference that carries a host) to the
right store, applying the air-gap gate: when ``security.airgap`` is set, any
remote target is refused while the local store keeps working.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from promptgenie.core.registry_store import (
    Descriptor,
    LocalRegistryStore,
    Manifest,
    Reference,
    RegistryError,
    RepoTag,
)


@runtime_checkable
class RegistryStore(Protocol):
    """The storage surface shared by the local and remote backends."""

    def put_blob(
        self, data: bytes, *, media_type: str, annotations: dict[str, str] | None = ...
    ) -> Descriptor: ...
    def get_blob(self, digest: str) -> bytes: ...
    def put_manifest(self, manifest: Manifest) -> str: ...
    def get_manifest(self, digest: str) -> Manifest: ...
    def manifest_digest_bytes(self, digest: str) -> bytes: ...
    def set_tag(self, repository: str, tag: str, manifest_digest: str) -> None: ...
    def resolve_ref(self, ref: Reference) -> str: ...
    def list_tags(self, repository: str) -> list[RepoTag]: ...
    def all_tags(self) -> list[RepoTag]: ...
    def remove_tag(self, repository: str, tag: str) -> None: ...
    def gc(self, *, dry_run: bool = ...) -> list[str]: ...
    def put_signature(self, manifest_digest: str, data: bytes, method: str) -> None: ...
    def find_signature(self, manifest_digest: str) -> tuple[str, bytes] | None: ...
    def has_signature(self, manifest_digest: str) -> bool: ...


def parse_remote(remote: str) -> tuple[str, str]:
    """Split a ``--remote`` value into ``(host, namespace)``.

    ``ghcr.io`` → ``("ghcr.io", "")``; ``ghcr.io/myorg`` → ``("ghcr.io", "myorg")``;
    ``https://reg.example.com/team/sub`` → ``("reg.example.com", "team/sub")``.
    """
    value = remote.strip()
    scheme = ""
    if "://" in value:
        scheme, value = value.split("://", 1)
    host, _, namespace = value.partition("/")
    if scheme:
        host = f"{scheme}://{host}"
    return host, namespace.strip("/")


def _base_url(host: str, *, insecure: bool) -> str:
    if "://" in host:
        return host
    return f"{'http' if insecure else 'https'}://{host}"


def _airgap_blocked() -> bool:
    try:
        from promptgenie.core.config import load_config

        return bool(load_config().security.airgap)
    except Exception:  # pragma: no cover - config errors fall through to allow
        return False


def _remote_store(host: str, repository: str, *, insecure: bool) -> RegistryStore:
    if _airgap_blocked():
        raise RegistryError(
            "Air-gap mode is enabled (security.airgap) — remote registry access is blocked. "
            "Use the local store, or disable with: promptgenie config set security.airgap false"
        )
    from promptgenie.core.registry_auth import get_token, normalize_host
    from promptgenie.core.registry_remote import RemoteRegistryStore

    token = get_token(normalize_host(host))
    return RemoteRegistryStore(
        _base_url(host, insecure=insecure), repository, token=token, insecure=insecure
    )


def resolve_push_target(
    remote: str | None, repository: str, *, store_path: str | None, insecure: bool = False
) -> tuple[RegistryStore, str]:
    """Return ``(store, full_repository)`` for a push.

    When *remote* is set the repository is prefixed by the remote's namespace.
    """
    if remote:
        host, namespace = parse_remote(remote)
        full_repo = f"{namespace}/{repository}" if namespace else repository
        return _remote_store(host, full_repo, insecure=insecure), full_repo
    return LocalRegistryStore(store_path), repository


def resolve_ref_target(
    ref: Reference,
    remote: str | None,
    *,
    store_path: str | None,
    insecure: bool = False,
) -> tuple[RegistryStore, Reference]:
    """Return ``(store, reference)`` for a pull/show/verify/tags request.

    A host embedded in the reference (``ghcr.io/org/x:v1``) selects the remote
    backend; otherwise ``--remote`` does; otherwise the local store is used. The
    returned reference is rewritten to the wire repository for remote targets.
    """
    if ref.host:
        return _remote_store(ref.host, ref.repository, insecure=insecure), ref
    if remote:
        host, namespace = parse_remote(remote)
        full_repo = f"{namespace}/{ref.repository}" if namespace else ref.repository
        rewritten = Reference(repository=full_repo, tag=ref.tag, digest=ref.digest, host=host)
        return _remote_store(host, full_repo, insecure=insecure), rewritten
    return LocalRegistryStore(store_path), ref


def is_remote(store: RegistryStore) -> bool:
    return not isinstance(store, LocalRegistryStore)
