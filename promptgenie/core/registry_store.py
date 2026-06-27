"""registry_store.py — content-addressable local store for prompt artifacts.

The prompt registry stores a prompt and everything it needs to run as an
**OCI-inspired, content-addressable artifact**: every input file is a
digest-named *blob*, a JSON *manifest* lists those blobs, and a tag *index* maps
``repository:tag`` to a manifest digest.

On-disk layout (``<root>`` defaults to ``~/.local/share/promptgenie/registry``)::

    <root>/
      blobs/sha256/<hex>        # every input file, stored once by content hash
      manifests/sha256/<hex>    # artifact manifest (canonical JSON), content hashed
      index.json                # repository -> {tag -> manifest digest}

Everything is verified by digest on read (fail-closed): a blob or manifest whose
content does not hash to its name raises :class:`RegistryError`. Digests are
validated as ``sha256:<64 hex>`` before they ever touch the filesystem, so a
crafted reference cannot escape the store directory.

This module is the storage substrate only — it knows nothing about PromptSpecs.
Building an artifact from a spec (layer enumeration) lives in ``artifact.py``;
the CLI lives in ``commands/registry_cmd.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Media types — OCI-inspired, namespaced to PromptGenie so strict-OCI adoption
# later (Phase B) is additive rather than breaking.
MANIFEST_MEDIA_TYPE = "application/vnd.promptgenie.prompt.manifest.v1+json"
CONFIG_MEDIA_TYPE = "application/vnd.promptgenie.prompt.config.v1+json"

LAYER_MEDIA_TYPES = {
    "spec": "application/vnd.promptgenie.spec.v1+yaml",
    "prompt": "application/vnd.promptgenie.prompt.v1+markdown",
    "template": "application/vnd.promptgenie.template.v1+markdown",
    "policy": "application/vnd.promptgenie.policy.v1+yaml",
    "context": "application/vnd.promptgenie.context.v1",
    "schema": "application/vnd.promptgenie.schema.v1+json",
    "vars": "application/vnd.promptgenie.vars.v1+yaml",
}

PATH_ANNOTATION = "org.promptgenie.path"
KIND_ANNOTATION = "org.promptgenie.kind"
SCHEMA_VERSION = 2

# Detached-signature file extensions, matching the pack-signing convention.
SIGNATURE_EXTS = {"minisign": ".minisig", "cosign": ".cosig"}

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# A repository is one or more lowercase path segments (namespace/name).
_REPO_SEG = r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
_REPO_RE = re.compile(rf"^{_REPO_SEG}(?:/{_REPO_SEG})*$")
_TAG_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$")

DEFAULT_TAG = "latest"


class RegistryError(Exception):
    """Raised on malformed references, digest mismatch, or missing objects."""


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reference:
    """A parsed artifact reference: ``[host/]repository[:tag][@digest]``."""

    repository: str
    tag: str | None = None
    digest: str | None = None
    host: str | None = None

    @classmethod
    def parse(cls, ref: str) -> Reference:
        if not ref or not ref.strip():
            raise RegistryError("Empty reference.")
        rest = ref.strip()

        digest: str | None = None
        if "@" in rest:
            rest, _, dig = rest.partition("@")
            if not _DIGEST_RE.match(dig):
                raise RegistryError(f"Invalid digest in reference: {dig!r} (want sha256:<64 hex>).")
            digest = dig

        # Optional host: first segment that looks like a domain or localhost.
        host: str | None = None
        if "/" in rest:
            head, _, tail = rest.partition("/")
            if head == "localhost" or "." in head or ":" in head:
                host = head
                rest = tail

        # Tag lives after the final '/', so a ':' there separates name:tag.
        tag: str | None = None
        last_slash = rest.rfind("/")
        name_part = rest[last_slash + 1 :]
        if ":" in name_part:
            base, _, t = name_part.rpartition(":")
            rest = rest[: last_slash + 1] + base
            tag = t

        repository = rest
        if not _REPO_RE.match(repository):
            raise RegistryError(
                f"Invalid repository name: {repository!r} "
                "(lowercase letters, digits, '.', '_', '-', '/' segments)."
            )
        if tag is not None and not _TAG_RE.match(tag):
            raise RegistryError(f"Invalid tag: {tag!r}.")

        # Default the tag to 'latest' only when no digest pin is given.
        if tag is None and digest is None:
            tag = DEFAULT_TAG

        return cls(repository=repository, tag=tag, digest=digest, host=host)

    @property
    def name(self) -> str:
        """The final path segment of the repository."""
        return self.repository.rsplit("/", 1)[-1]

    def __str__(self) -> str:
        s = f"{self.host}/{self.repository}" if self.host else self.repository
        if self.tag:
            s += f":{self.tag}"
        if self.digest:
            s += f"@{self.digest}"
        return s


# ---------------------------------------------------------------------------
# Descriptors & manifests
# ---------------------------------------------------------------------------


@dataclass
class Descriptor:
    """A pointer to a content-addressed blob (OCI descriptor shape)."""

    media_type: str
    digest: str
    size: int
    annotations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {"mediaType": self.media_type, "digest": self.digest, "size": self.size}
        if self.annotations:
            d["annotations"] = dict(self.annotations)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Descriptor:
        return cls(
            media_type=str(d["mediaType"]),
            digest=str(d["digest"]),
            size=int(d["size"]),
            annotations=dict(d.get("annotations") or {}),
        )


@dataclass
class Manifest:
    config: Descriptor
    layers: list[Descriptor] = field(default_factory=list)
    annotations: dict[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    media_type: str = MANIFEST_MEDIA_TYPE

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "mediaType": self.media_type,
            "config": self.config.to_dict(),
            "layers": [layer.to_dict() for layer in self.layers],
            "annotations": dict(self.annotations),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Manifest:
        return cls(
            config=Descriptor.from_dict(d["config"]),
            layers=[Descriptor.from_dict(x) for x in d.get("layers", [])],
            annotations=dict(d.get("annotations") or {}),
            schema_version=int(d.get("schemaVersion", SCHEMA_VERSION)),
            media_type=str(d.get("mediaType", MANIFEST_MEDIA_TYPE)),
        )

    def canonical_bytes(self) -> bytes:
        """Stable serialization used for the manifest digest and on-disk form."""
        return canonical_json(self.to_dict())


def canonical_json(obj: object) -> bytes:
    """Deterministic JSON encoding (sorted keys, no whitespace) for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _digest_hex(digest: str) -> str:
    if not _DIGEST_RE.match(digest):
        raise RegistryError(f"Invalid digest: {digest!r} (want sha256:<64 hex>).")
    return digest.split(":", 1)[1]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def default_store_root() -> Path:
    """User-global store root (overridable by config / --store-path)."""
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "promptgenie" / "registry"


@dataclass
class RepoTag:
    repository: str
    tag: str
    digest: str


class LocalRegistryStore:
    """A filesystem-backed content-addressable store."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else default_store_root()
        self.blobs_dir = self.root / "blobs" / "sha256"
        self.manifests_dir = self.root / "manifests" / "sha256"
        self.signatures_dir = self.root / "signatures" / "sha256"
        self.index_path = self.root / "index.json"

    # -- low-level blob/manifest IO ----------------------------------------

    def _atomic_write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".pg_tmp_", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def blob_path(self, digest: str) -> Path:
        return self.blobs_dir / _digest_hex(digest)

    def has_blob(self, digest: str) -> bool:
        return self.blob_path(digest).exists()

    def put_blob(self, data: bytes, *, media_type: str, annotations: dict[str, str] | None = None) -> Descriptor:
        digest = compute_digest(data)
        path = self.blob_path(digest)
        if not path.exists():  # content-addressed: identical content is a no-op
            self._atomic_write(path, data)
        return Descriptor(media_type, digest, len(data), dict(annotations or {}))

    def get_blob(self, digest: str) -> bytes:
        path = self.blob_path(digest)
        if not path.exists():
            raise RegistryError(f"Blob not found: {digest}")
        data = path.read_bytes()
        actual = compute_digest(data)
        if actual != digest:
            raise RegistryError(f"Blob digest mismatch for {digest}: content hashes to {actual}.")
        return data

    def put_manifest(self, manifest: Manifest) -> str:
        data = manifest.canonical_bytes()
        digest = compute_digest(data)
        path = self.manifests_dir / _digest_hex(digest)
        if not path.exists():
            self._atomic_write(path, data)
        return digest

    def get_manifest(self, digest: str) -> Manifest:
        path = self.manifests_dir / _digest_hex(digest)
        if not path.exists():
            raise RegistryError(f"Manifest not found: {digest}")
        data = path.read_bytes()
        actual = compute_digest(data)
        if actual != digest:
            raise RegistryError(f"Manifest digest mismatch for {digest}: content hashes to {actual}.")
        return Manifest.from_dict(json.loads(data))

    def manifest_digest_bytes(self, digest: str) -> bytes:
        """Raw on-disk manifest bytes (used for signature verification)."""
        path = self.manifests_dir / _digest_hex(digest)
        if not path.exists():
            raise RegistryError(f"Manifest not found: {digest}")
        return path.read_bytes()

    # -- signatures --------------------------------------------------------

    def signature_path(self, manifest_digest: str, method: str) -> Path:
        if method not in SIGNATURE_EXTS:
            raise RegistryError(f"Unknown signing method: {method!r}.")
        return self.signatures_dir / (_digest_hex(manifest_digest) + SIGNATURE_EXTS[method])

    def put_signature(self, manifest_digest: str, data: bytes, method: str) -> None:
        self._atomic_write(self.signature_path(manifest_digest, method), data)

    def find_signature(self, manifest_digest: str) -> tuple[str, bytes] | None:
        """Return ``(method, signature_bytes)`` for *manifest_digest*, if signed."""
        for method in SIGNATURE_EXTS:
            path = self.signature_path(manifest_digest, method)
            if path.exists():
                return method, path.read_bytes()
        return None

    def has_signature(self, manifest_digest: str) -> bool:
        return self.find_signature(manifest_digest) is not None

    # -- index / tags ------------------------------------------------------

    def _load_index(self) -> dict:
        if not self.index_path.exists():
            return {"schema_version": "1.0", "repositories": {}}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"Corrupt registry index: {exc}") from exc
        if not isinstance(data, dict) or "repositories" not in data:
            raise RegistryError("Corrupt registry index: missing 'repositories'.")
        return data

    def _save_index(self, index: dict) -> None:
        self._atomic_write(self.index_path, canonical_json(index) + b"\n")

    def set_tag(self, repository: str, tag: str, manifest_digest: str) -> None:
        _digest_hex(manifest_digest)  # validate
        index = self._load_index()
        repos = index["repositories"]
        entry = repos.setdefault(repository, {"tags": {}, "updated_at": ""})
        entry["tags"][tag] = manifest_digest
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_index(index)

    def resolve_ref(self, ref: Reference) -> str:
        """Resolve a reference to a manifest digest (digest pin or repo:tag)."""
        if ref.digest:
            return ref.digest
        index = self._load_index()
        repo = index["repositories"].get(ref.repository)
        if not repo:
            raise RegistryError(f"Repository not found: {ref.repository}")
        tag = ref.tag or DEFAULT_TAG
        digest = repo["tags"].get(tag)
        if not digest:
            raise RegistryError(f"Tag not found: {ref.repository}:{tag}")
        return str(digest)

    def list_repos(self) -> list[str]:
        return sorted(self._load_index()["repositories"].keys())

    def list_tags(self, repository: str) -> list[RepoTag]:
        repo = self._load_index()["repositories"].get(repository)
        if not repo:
            return []
        return [RepoTag(repository, t, d) for t, d in sorted(repo["tags"].items())]

    def all_tags(self) -> list[RepoTag]:
        out: list[RepoTag] = []
        for repository, repo in sorted(self._load_index()["repositories"].items()):
            for tag, digest in sorted(repo["tags"].items()):
                out.append(RepoTag(repository, tag, digest))
        return out

    def remove_tag(self, repository: str, tag: str) -> None:
        index = self._load_index()
        repo = index["repositories"].get(repository)
        if not repo or tag not in repo["tags"]:
            raise RegistryError(f"Tag not found: {repository}:{tag}")
        del repo["tags"][tag]
        if not repo["tags"]:
            del index["repositories"][repository]
        self._save_index(index)

    # -- garbage collection ------------------------------------------------

    def gc(self, *, dry_run: bool = False) -> list[str]:
        """Remove manifests and blobs no longer referenced by any tag.

        Returns the digests that were (or would be) removed.
        """
        referenced_manifests: set[str] = set()
        referenced_blobs: set[str] = set()
        for rt in self.all_tags():
            referenced_manifests.add(rt.digest)
            try:
                manifest = self.get_manifest(rt.digest)
            except RegistryError:
                continue
            referenced_blobs.add(manifest.config.digest)
            for layer in manifest.layers:
                referenced_blobs.add(layer.digest)

        removed: list[str] = []
        for path, referenced in (
            (self.manifests_dir, referenced_manifests),
            (self.blobs_dir, referenced_blobs),
        ):
            if not path.exists():
                continue
            for f in path.iterdir():
                if not f.is_file():
                    continue
                digest = f"sha256:{f.name}"
                if digest not in referenced:
                    removed.append(digest)
                    if not dry_run:
                        f.unlink()

        # Drop signatures whose manifest is no longer referenced.
        if self.signatures_dir.exists():
            ref_hex = {_digest_hex(d) for d in referenced_manifests}
            for f in self.signatures_dir.iterdir():
                if f.is_file() and f.stem not in ref_hex and not dry_run:
                    f.unlink()
        return removed
