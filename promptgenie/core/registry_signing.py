"""registry_signing.py — sign and verify prompt-artifact manifests.

The registry signs the **manifest blob** (whose digest transitively covers every
layer), so one signature attests to the whole artifact. Signatures are detached
and stored in the registry alongside the manifest
(``signatures/sha256/<manifest-hex>.{minisig,cosig}``).

The cryptography itself is delegated to :mod:`promptgenie.core.pack_signing`
(``minisign`` / ``cosign`` subprocesses); this module only orchestrates writing
the manifest bytes to a temp file, invoking sign/verify, and storing/reading the
detached signature in the registry store.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from promptgenie.core.pack_signing import sign_blob_file, verify_pack_signature
from promptgenie.core.registry_store import SIGNATURE_EXTS, RegistryError

if TYPE_CHECKING:
    from promptgenie.core.registry_backend import RegistryStore


def sign_manifest(
    store: RegistryStore,
    manifest_digest: str,
    secret_key: str,
    method: str = "minisign",
) -> None:
    """Sign the stored manifest *manifest_digest* and persist the signature."""
    if method not in SIGNATURE_EXTS:
        raise RegistryError(f"Unknown signing method: {method!r}.")
    data = store.manifest_digest_bytes(manifest_digest)
    with tempfile.TemporaryDirectory() as tmp:
        blob = Path(tmp) / "manifest"
        blob.write_bytes(data)
        sig_path = sign_blob_file(blob, secret_key, method=method)
        store.put_signature(manifest_digest, sig_path.read_bytes(), method)


def verify_manifest(
    store: RegistryStore,
    manifest_digest: str,
    pubkey: str,
    method: str | None = None,
) -> bool:
    """Verify the detached signature over *manifest_digest*.

    With *method* unset, the stored signature's method is auto-detected. Returns
    ``False`` when no signature is present or verification fails.
    """
    found = store.find_signature(manifest_digest)
    if found is None:
        return False
    stored_method, sig_bytes = found
    method = method or stored_method
    if method != stored_method:
        return False
    data = store.manifest_digest_bytes(manifest_digest)
    ext = SIGNATURE_EXTS[method]
    with tempfile.TemporaryDirectory() as tmp:
        blob = Path(tmp) / "manifest"
        blob.write_bytes(data)
        # pack_signing expects the detached signature adjacent to the blob.
        (Path(tmp) / f"manifest{ext}").write_bytes(sig_bytes)
        return verify_pack_signature(blob, pubkey, method=method)
