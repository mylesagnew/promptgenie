"""registry_remote.py — OCI-registry backend for the prompt registry (Phase B.1).

``RemoteRegistryStore`` is a **repository-bound** client: one instance targets a
single ``host/repository`` over the OCI distribution API. Because it is bound to a
repository, its method signatures match the repo-agnostic
:class:`~promptgenie.core.registry_store.LocalRegistryStore`, so the existing
``push_bundle`` / ``materialise`` / ``registry_signing`` helpers work against it
unchanged — the only difference is where the bytes live.

Trust model
-----------
The registry server is **untrusted**. Every blob and manifest fetched from it is
verified client-side against its digest (fail-closed); a digest pin or a
``--require-signed`` + pinned public key gives end-to-end integrity regardless of
the transport or the registry operator.

Wire format
-----------
Manifests are pushed as OCI image manifests
(``application/vnd.oci.image.manifest.v1+json``) carrying our config + layers and
PromptGenie kinds in layer annotations. Detached signatures use a cosign-style
``sha256-<hex>.sig`` tag pointing at a one-layer manifest whose blob is the
signature (interoperable PromptGenie↔PromptGenie across any OCI registry).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from promptgenie.core.registry_store import (
    Descriptor,
    Manifest,
    Reference,
    RegistryError,
    RepoTag,
    compute_digest,
)

OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
_SIG_MEDIA_TYPES = {
    "minisign": "application/vnd.promptgenie.signature.minisign",
    "cosign": "application/vnd.promptgenie.signature.cosign",
}
_MEDIA_TO_METHOD = {v: k for k, v in _SIG_MEDIA_TYPES.items()}

_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024  # 64 MB cap per object


def _require_https(base_url: str, *, insecure: bool) -> None:
    scheme = base_url.split("://", 1)[0].lower() if "://" in base_url else ""
    if scheme == "https":
        return
    if scheme == "http" and insecure:
        return
    raise RegistryError(
        f"Refusing non-HTTPS registry URL {base_url!r}. Use https:// (or --insecure for http)."
    )


@dataclass
class RemoteRegistryStore:
    """OCI-distribution client bound to one ``host/repository``."""

    base_url: str
    repository: str
    token: str | None = None
    insecure: bool = False
    client: Any = None  # httpx.Client; injected in tests
    max_bytes: int = _MAX_DOWNLOAD_BYTES

    def __post_init__(self) -> None:
        self._manifest_cache: dict[str, bytes] = {}
        self._client: Any
        if self.client is None:
            _require_https(self.base_url, insecure=self.insecure)
            import httpx

            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            self._client = httpx.Client(
                base_url=self.base_url.rstrip("/"),
                headers=headers,
                verify=not self.insecure,
                timeout=30.0,
                follow_redirects=True,
            )
        else:
            self._client = self.client

    # -- HTTP helpers ------------------------------------------------------

    def _url(self, suffix: str) -> str:
        return f"/v2/{self.repository}/{suffix}"

    def _check(self, resp, *, ok: tuple[int, ...]):
        if resp.status_code not in ok:
            body = resp.text[:200] if hasattr(resp, "text") else ""
            raise RegistryError(
                f"{resp.request.method} {resp.request.url} → {resp.status_code}. {body}".strip()
            )
        return resp

    # -- blobs -------------------------------------------------------------

    def has_blob(self, digest: str) -> bool:
        resp = self._client.head(self._url(f"blobs/{digest}"))
        return bool(resp.status_code == 200)

    def put_blob(
        self, data: bytes, *, media_type: str, annotations: dict[str, str] | None = None
    ) -> Descriptor:
        digest = compute_digest(data)
        if not self.has_blob(digest):  # dedup — upload shared layers once
            start = self._check(
                self._client.post(self._url("blobs/uploads/")), ok=(201, 202)
            )
            location = start.headers.get("Location")
            if not location:
                raise RegistryError("Registry did not return an upload Location.")
            sep = "&" if "?" in location else "?"
            self._check(
                self._client.put(
                    f"{location}{sep}digest={digest}",
                    content=data,
                    headers={"Content-Type": "application/octet-stream"},
                ),
                ok=(201,),
            )
        return Descriptor(media_type, digest, len(data), dict(annotations or {}))

    def get_blob(self, digest: str) -> bytes:
        resp = self._check(self._client.get(self._url(f"blobs/{digest}")), ok=(200,))
        data = resp.content
        if len(data) > self.max_bytes:
            raise RegistryError(f"Blob {digest} exceeds {self.max_bytes} byte cap.")
        actual = compute_digest(data)
        if actual != digest:
            raise RegistryError(f"Blob digest mismatch for {digest}: server sent {actual}.")
        return cast(bytes, data)

    # -- manifests ---------------------------------------------------------

    def _oci_bytes(self, manifest: Manifest) -> bytes:
        manifest.media_type = OCI_MANIFEST_MEDIA_TYPE
        return manifest.canonical_bytes()

    def put_manifest(self, manifest: Manifest) -> str:
        data = self._oci_bytes(manifest)
        digest = compute_digest(data)
        self._manifest_cache[digest] = data
        self._put_manifest_bytes(digest, data)
        return digest

    def _put_manifest_bytes(self, reference: str, data: bytes) -> None:
        self._check(
            self._client.put(
                self._url(f"manifests/{reference}"),
                content=data,
                headers={"Content-Type": OCI_MANIFEST_MEDIA_TYPE},
            ),
            ok=(201,),
        )

    def set_tag(self, repository: str, tag: str, manifest_digest: str) -> None:
        data = self._manifest_cache.get(manifest_digest) or self.manifest_digest_bytes(manifest_digest)
        self._put_manifest_bytes(tag, data)

    def _get_manifest_bytes(self, reference: str) -> bytes:
        resp = self._check(
            self._client.get(
                self._url(f"manifests/{reference}"),
                headers={"Accept": OCI_MANIFEST_MEDIA_TYPE},
            ),
            ok=(200,),
        )
        data = resp.content
        if len(data) > self.max_bytes:
            raise RegistryError(f"Manifest {reference} exceeds {self.max_bytes} byte cap.")
        return cast(bytes, data)

    def manifest_digest_bytes(self, digest: str) -> bytes:
        data = self._get_manifest_bytes(digest)
        actual = compute_digest(data)
        if actual != digest:
            raise RegistryError(f"Manifest digest mismatch for {digest}: server sent {actual}.")
        return cast(bytes, data)

    def get_manifest(self, digest: str) -> Manifest:
        return Manifest.from_dict(json.loads(self.manifest_digest_bytes(digest)))

    def resolve_ref(self, ref: Reference) -> str:
        if ref.digest:
            return ref.digest
        tag = ref.tag or "latest"
        data = self._get_manifest_bytes(tag)
        return compute_digest(data)

    # -- tags --------------------------------------------------------------

    def list_tags(self, repository: str | None = None) -> list[RepoTag]:
        resp = self._client.get(self._url("tags/list"))
        if resp.status_code != 200:
            return []
        body = resp.json()
        return [RepoTag(self.repository, t, "") for t in body.get("tags", []) if not t.endswith(".sig")]

    def all_tags(self) -> list[RepoTag]:
        return self.list_tags(self.repository)

    def remove_tag(self, repository: str, tag: str) -> None:
        raise RegistryError("Tag deletion is managed server-side on remote registries.")

    def gc(self, *, dry_run: bool = False) -> list[str]:
        raise RegistryError("Garbage collection is managed server-side on remote registries.")

    # -- signatures (cosign-style .sig tag) --------------------------------

    @staticmethod
    def _sig_tag(manifest_digest: str) -> str:
        return manifest_digest.replace(":", "-") + ".sig"

    def put_signature(self, manifest_digest: str, data: bytes, method: str) -> None:
        media = _SIG_MEDIA_TYPES.get(method)
        if media is None:
            raise RegistryError(f"Unknown signing method: {method!r}.")
        sig_layer = self.put_blob(data, media_type=media)
        config = self.put_blob(b"{}", media_type="application/vnd.oci.empty.v1+json")
        sig_manifest = Manifest(
            config=config,
            layers=[sig_layer],
            annotations={"org.promptgenie.signs": manifest_digest},
        )
        sig_bytes = self._oci_bytes(sig_manifest)
        self._put_manifest_bytes(self._sig_tag(manifest_digest), sig_bytes)

    def find_signature(self, manifest_digest: str) -> tuple[str, bytes] | None:
        try:
            data = self._get_manifest_bytes(self._sig_tag(manifest_digest))
        except RegistryError:
            return None
        manifest = Manifest.from_dict(json.loads(data))
        if not manifest.layers:
            return None
        layer = manifest.layers[0]
        method = _MEDIA_TO_METHOD.get(layer.media_type)
        if method is None:
            return None
        return method, self.get_blob(layer.digest)

    def has_signature(self, manifest_digest: str) -> bool:
        return self.find_signature(manifest_digest) is not None

    def close(self) -> None:
        if self.client is None and hasattr(self._client, "close"):
            self._client.close()
