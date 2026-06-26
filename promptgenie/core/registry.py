"""
registry.py — remote profile and rule pack registry.

The registry is a simple YAML index (hosted on GitHub or self-hosted) listing
available packs. Each pack is a YAML file that can be installed locally and
then referenced by name in CLI commands or config.

Pack types
----------
  rules    — bundle of scanner_rules and/or lint_rules
  context  — context pack (same format as built-in context-packs/*.yaml)
  profile  — target profile (same format as built-in profiles/*.yaml)

User data directory layout
--------------------------
  ~/.promptgenie/
    registry/
      index.yaml          # cached remote index (written by `pack update`)
      packs/
        owasp-llm-top10.yaml
        ...
    rules/                # user's own custom rule pack files (rules_dirs default)

Built-in registry
-----------------
  promptgenie/registry/index.yaml   — shipped with the package, always available
  promptgenie/registry/packs/*.yaml — starter packs, available without network

Network access
--------------
  `pack update`  — fetches the remote index and downloads new/updated packs.
  `pack install` — downloads a single pack from the registry URL.

  All network calls use urllib.request (stdlib, no extra deps).
  If the network is unavailable, commands gracefully fall back to the
  built-in index and any already-installed packs.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import tarfile

from promptgenie.core.fileio import safe_read_yaml, safe_write_text

# ── constants ─────────────────────────────────────────────────────────────────

# Only HTTPS is permitted for remote registry and pack downloads.
# file://, http://, ftp://, data:, and custom schemes are blocked.
_ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"https"})

# Maximum bytes accepted from a single network response (1 MiB).
# Prevents memory exhaustion from malicious or misconfigured servers.
_MAX_DOWNLOAD_BYTES: int = 1 * 1024 * 1024  # 1 MiB

# A pack id is used to build the on-disk filename ``<id>.yaml``. Constrain it to
# a conservative charset so a crafted tarball can never traverse directories or
# overwrite arbitrary files via the derived destination path.
_SAFE_PACK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# ── paths ──────────────────────────────────────────────────────────────────────

BUILTIN_REGISTRY_DIR = Path(__file__).parent.parent / "registry"
BUILTIN_INDEX_PATH = BUILTIN_REGISTRY_DIR / "index.yaml"
BUILTIN_PACKS_DIR = BUILTIN_REGISTRY_DIR / "packs"

USER_DIR = Path.home() / ".promptgenie"
USER_REGISTRY_DIR = USER_DIR / "registry"
USER_PACKS_DIR = USER_REGISTRY_DIR / "packs"
USER_RULES_DIR = USER_DIR / "rules"
CACHED_INDEX_PATH = USER_REGISTRY_DIR / "index.yaml"

DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/mylesagnew/promptgenie/main/promptgenie/registry/index.yaml"
)

# ── data types ────────────────────────────────────────────────────────────────


@dataclass
class RegistryEntry:
    """A single entry from the registry index."""

    id: str
    name: str
    version: str
    description: str
    type: str  # "rules" | "context" | "profile"
    url: str
    sha256: str = ""

    def is_installed(self, install_dir: Path | None = None) -> bool:
        d = install_dir or USER_PACKS_DIR
        return (d / f"{self.id}.yaml").exists()


@dataclass
class InstalledPack:
    """Metadata for a locally installed pack."""

    id: str
    name: str
    version: str
    type: str
    path: Path
    source: str = "registry"  # "builtin" | "registry" | "local"


@dataclass
class UpdateResult:
    installed: list[str] = field(default_factory=list)  # newly installed
    updated: list[str] = field(default_factory=list)  # updated to newer version
    skipped: list[str] = field(default_factory=list)  # already up-to-date
    errors: list[str] = field(default_factory=list)  # download/verify failures


# ── index loading ─────────────────────────────────────────────────────────────


def _parse_index(raw: dict) -> list[RegistryEntry]:
    entries = []
    for item in raw.get("packs", []):
        if not isinstance(item, dict):
            continue
        pack_id = str(item.get("id", "")).strip()
        if not pack_id:
            continue
        entries.append(
            RegistryEntry(
                id=pack_id,
                name=str(item.get("name", pack_id)),
                version=str(item.get("version", "0.0.0")),
                description=str(item.get("description", "")),
                type=str(item.get("type", "rules")),
                url=str(item.get("url", "")),
                sha256=str(item.get("sha256", "")),
            )
        )
    return entries


def load_builtin_index() -> list[RegistryEntry]:
    """Return entries from the built-in registry index shipped with the package."""
    raw = safe_read_yaml(BUILTIN_INDEX_PATH) or {}
    return _parse_index(raw)


def load_cached_index() -> list[RegistryEntry]:
    """Return entries from the locally cached remote index, if present."""
    if not CACHED_INDEX_PATH.exists():
        return []
    raw = safe_read_yaml(CACHED_INDEX_PATH) or {}
    return _parse_index(raw)


def load_index(prefer_cached: bool = True) -> list[RegistryEntry]:
    """Load the registry index.

    Returns the cached remote index if available (and *prefer_cached* is True),
    falling back to the built-in index.
    """
    if prefer_cached:
        cached = load_cached_index()
        if cached:
            return cached
    return load_builtin_index()


def _validate_url(url: str) -> None:
    """Raise ``ValueError`` if *url* uses a disallowed scheme.

    Only HTTPS is permitted. ``file://``, ``http://``, ``ftp://``, ``data:``,
    and any custom schemes are rejected to prevent SSRF-style local file
    exfiltration via a poisoned registry index.
    """
    if not url:
        raise ValueError("Pack URL must not be empty.")
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"Disallowed URL scheme {parsed.scheme!r} in pack URL {url!r}. "
            f"Only {sorted(_ALLOWED_URL_SCHEMES)} are permitted."
        )


def fetch_remote_index(url: str = DEFAULT_REGISTRY_URL, timeout: int = 10) -> list[RegistryEntry]:
    """Fetch the registry index from *url* and return parsed entries.

    Raises ``ValueError`` on disallowed URL scheme.
    Raises ``urllib.error.URLError`` / ``OSError`` on network failure.
    """
    _validate_url(url)
    # scheme validated by _validate_url above
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310  # nosec B310
        import yaml

        data = resp.read(_MAX_DOWNLOAD_BYTES + 1)
    if len(data) > _MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"Registry index download exceeded {_MAX_DOWNLOAD_BYTES} byte limit "
            f"(got ≥{len(data)} bytes from {url!r}). Aborting."
        )
    raw = yaml.safe_load(data.decode("utf-8")) or {}
    return _parse_index(raw)


# ── pack installation ─────────────────────────────────────────────────────────


def _verify_sha256(path: Path, expected: str) -> bool:
    """Return True if *path* matches *expected* SHA-256 hex digest (or expected is empty)."""
    if not expected:
        return True  # no checksum provided — skip verification
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest == expected.lower().removeprefix("sha256:")


def _download_to_temp(url: str, timeout: int = 30, max_bytes: int = _MAX_DOWNLOAD_BYTES) -> Path:
    """Download *url* to a temp file and return its path.

    Raises ``ValueError`` on disallowed scheme or response exceeding *max_bytes*.
    Uses ``mkstemp`` to avoid TOCTOU races (no ``mktemp``).
    """
    _validate_url(url)
    # scheme validated by _validate_url above
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310  # nosec B310
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(
            f"Pack download exceeded {max_bytes} byte limit "
            f"(got ≥{len(data)} bytes from {url!r}). Aborting."
        )
    fd, tmp_str = tempfile.mkstemp(suffix=".yaml")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return Path(tmp_str)


def install_pack(
    entry: RegistryEntry,
    install_dir: Path | None = None,
    timeout: int = 30,
    require_checksum: bool = False,
) -> Path:
    """Download and install a single pack from *entry.url*.

    Returns the path of the installed file.

    Args:
        entry:             Registry entry describing the pack to install.
        install_dir:       Directory to install into (default: ``USER_PACKS_DIR``).
        timeout:           Network timeout in seconds.
        require_checksum:  If ``True``, raise ``ValueError`` when the registry
                           entry has no ``sha256`` field.  Defaults to ``False``
                           for backwards compatibility with existing index entries
                           that carry empty checksums; set ``True`` in strict CI
                           environments.

    Raises:
        ``ValueError`` on disallowed URL scheme, checksum absence (strict mode),
        or checksum mismatch.
        ``urllib.error.URLError`` / ``OSError`` on network failure.
    """
    if require_checksum and not entry.sha256:
        raise ValueError(
            f"Pack '{entry.id}' has no SHA-256 checksum in the registry index. "
            "Update the index with a sha256 field, or pass require_checksum=False "
            "to skip integrity verification."
        )

    dest_dir = install_dir or USER_PACKS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{entry.id}.yaml"

    tmp = _download_to_temp(entry.url, timeout=timeout)
    try:
        if entry.sha256 and not _verify_sha256(tmp, entry.sha256):
            raise ValueError(
                f"SHA-256 mismatch for pack '{entry.id}'. "
                f"Expected {entry.sha256}, "
                f"got {hashlib.sha256(tmp.read_bytes()).hexdigest()}"
            )
        shutil.move(str(tmp), str(dest))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    return dest


# ── local install (air-gap / offline) ─────────────────────────────────────────


def install_from_local(
    source: str | Path,
    install_dir: Path | None = None,
    expected_sha256: str | None = None,
) -> Path:
    """Install a pack from a local file path (YAML or .tar.gz tarball).

    Supports two source formats:
    * Single YAML file — copied directly into *install_dir*.
    * ``.tar.gz`` tarball — extracted; must contain exactly one ``pack.yaml``
      (or a ``*.yaml`` matching the pack id at the archive root).

    Parameters
    ----------
    source:
        Path to a local ``.yaml`` or ``.tar.gz`` file.
    install_dir:
        Directory to install into. Defaults to ``USER_PACKS_DIR``.
    expected_sha256:
        Optional SHA-256 hex digest to verify the source file before install.
        Raises ``ValueError`` on mismatch.

    Returns the path of the installed YAML file.
    """
    import tarfile as _tarfile

    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(f"Local pack source not found: {src}")

    dest_dir = install_dir or USER_PACKS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Optional integrity check
    if expected_sha256 and not _verify_sha256(src, expected_sha256):
        actual = hashlib.sha256(src.read_bytes()).hexdigest()
        raise ValueError(
            f"SHA-256 mismatch for local pack {src.name}. Expected {expected_sha256}, got {actual}"
        )

    if src.suffix.lower() == ".yaml":
        dest = dest_dir / src.name
        shutil.copy2(str(src), str(dest))
        return dest

    if src.name.endswith(".tar.gz") or src.suffix.lower() == ".tgz":
        # Never extract the tarball to disk. Select a single manifest member,
        # validate it (regular file only — no symlinks, devices, hardlinks,
        # absolute paths, or ``..``), and stream just that member into memory
        # via ``extractfile``. This removes the Tar-Slip vector entirely rather
        # than guarding an ``extractall`` call.
        import yaml

        with _tarfile.open(src, "r:gz") as tf:
            pack_member = _select_pack_member(tf.getmembers(), src.name)
            _assert_safe_tar_member(pack_member)

            extracted = tf.extractfile(pack_member)
            if extracted is None:
                raise ValueError(
                    f"Pack manifest {pack_member.name!r} in {src.name} is not a readable file."
                )
            with extracted:
                raw_bytes = extracted.read(_MAX_DOWNLOAD_BYTES + 1)

        if len(raw_bytes) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"Pack manifest in {src.name} exceeds the {_MAX_DOWNLOAD_BYTES} byte limit."
            )

        text = raw_bytes.decode("utf-8")
        parsed = yaml.safe_load(text) or {}
        if not isinstance(parsed, dict):
            raise ValueError(f"Pack manifest in {src.name} is not a valid YAML mapping.")

        pack_id = _safe_pack_id(parsed.get("id") or PurePosixPath(pack_member.name).stem)
        dest = dest_dir / f"{pack_id}.yaml"
        safe_write_text(dest, text, force=True)
        return dest

    raise ValueError(
        f"Unsupported local pack format: {src.name!r}. Use a .yaml file or a .tar.gz tarball."
    )


def _select_pack_member(members: list[tarfile.TarInfo], archive_name: str) -> tarfile.TarInfo:
    """Pick the manifest member from a pack tarball without extracting anything.

    Prefers a regular-file member whose basename is ``pack.yaml``; otherwise the
    first ``*.yaml`` regular-file member in sorted (deterministic) order.

    Raises ``ValueError`` if no candidate YAML member exists.
    """
    yaml_members = sorted(
        (m for m in members if m.isreg() and m.name.lower().endswith(".yaml")),
        key=lambda m: m.name,
    )
    if not yaml_members:
        raise ValueError(
            f"No YAML file found in tarball {archive_name}. "
            "A pack tarball must contain a pack.yaml or <pack-id>.yaml file."
        )
    for m in yaml_members:
        if PurePosixPath(m.name).name == "pack.yaml":
            return m
    return yaml_members[0]


def _assert_safe_tar_member(member: tarfile.TarInfo) -> None:
    """Raise ``ValueError`` unless *member* is a safe regular file.

    Rejects symlinks, hardlinks, character/block devices, FIFOs, directories,
    absolute paths, and ``..`` traversal sequences.
    """
    name = member.name
    if member.issym() or member.islnk():
        raise ValueError(f"Pack tarball member is a link (unsafe): {name!r}")
    if member.isdev() or member.isfifo():
        raise ValueError(f"Pack tarball member is a special/device file (unsafe): {name!r}")
    if not member.isreg():
        raise ValueError(f"Pack tarball member is not a regular file: {name!r}")

    pure = PurePosixPath(name)
    if pure.is_absolute() or os.path.isabs(name):
        raise ValueError(f"Pack tarball member has an absolute path (unsafe): {name!r}")
    if ".." in pure.parts:
        raise ValueError(f"Pack tarball member contains path traversal (unsafe): {name!r}")


def _safe_pack_id(raw_id: object) -> str:
    """Return *raw_id* if it is a safe pack id, else raise ``ValueError``.

    The id becomes the on-disk filename ``<id>.yaml``; anything that could
    traverse directories or escape the install dir is rejected.
    """
    pack_id = str(raw_id).strip()
    if not pack_id or "/" in pack_id or "\\" in pack_id or not _SAFE_PACK_ID_RE.match(pack_id):
        raise ValueError(f"Unsafe or invalid pack id derived from tarball: {raw_id!r}")
    return pack_id


# ── update ────────────────────────────────────────────────────────────────────


def _installed_version(pack_id: str, install_dir: Path) -> str:
    """Return the version string of an installed pack, or "" if not installed."""
    path = install_dir / f"{pack_id}.yaml"
    if not path.exists():
        return ""
    raw = safe_read_yaml(path) or {}
    return str(raw.get("version", ""))


def update_registry(
    url: str = DEFAULT_REGISTRY_URL,
    install_dir: Path | None = None,
    timeout: int = 30,
    require_checksum: bool = True,
) -> UpdateResult:
    """Fetch the remote index and install/update all packs.

    Caches the fetched index to ``CACHED_INDEX_PATH`` on success.
    Returns an ``UpdateResult`` summarising what happened.

    Args:
        url:               Remote registry index URL.
        install_dir:       Directory to install packs into (default: ``USER_PACKS_DIR``).
        timeout:           Network timeout in seconds.
        require_checksum:  If ``True`` (default), packs without a ``sha256`` in the index
                           are refused.  Pass ``False`` only when using a private registry
                           that does not yet publish checksums.
    """
    result = UpdateResult()
    dest_dir = install_dir or USER_PACKS_DIR

    try:
        entries = fetch_remote_index(url, timeout=timeout)
    except (urllib.error.URLError, OSError) as exc:
        result.errors.append(f"Failed to fetch registry index from {url}: {exc}")
        return result

    # Cache the fetched index
    try:
        CACHED_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        import yaml

        index_raw = {
            "format_version": "1",
            "packs": [
                {
                    "id": e.id,
                    "name": e.name,
                    "version": e.version,
                    "description": e.description,
                    "type": e.type,
                    "url": e.url,
                    "sha256": e.sha256,
                }
                for e in entries
            ],
        }
        safe_write_text(
            CACHED_INDEX_PATH, yaml.dump(index_raw, default_flow_style=False), force=True
        )
    except Exception:
        pass  # cache write failure is non-fatal

    for entry in entries:
        try:
            installed_ver = _installed_version(entry.id, dest_dir)
            if not installed_ver:
                install_pack(
                    entry,
                    install_dir=dest_dir,
                    timeout=timeout,
                    require_checksum=require_checksum,
                )
                result.installed.append(entry.id)
            elif installed_ver != entry.version:
                install_pack(
                    entry,
                    install_dir=dest_dir,
                    timeout=timeout,
                    require_checksum=require_checksum,
                )
                result.updated.append(entry.id)
            else:
                result.skipped.append(entry.id)
        except Exception as exc:
            result.errors.append(f"{entry.id}: {exc}")

    return result


# ── installed packs listing ───────────────────────────────────────────────────


def list_installed_packs(install_dir: Path | None = None) -> list[InstalledPack]:
    """Return metadata for all packs installed in *install_dir*."""
    dest_dir = install_dir or USER_PACKS_DIR
    packs: list[InstalledPack] = []
    if not dest_dir.exists():
        return packs
    for yaml_file in sorted(dest_dir.glob("*.yaml")):
        raw = safe_read_yaml(yaml_file) or {}
        packs.append(
            InstalledPack(
                id=yaml_file.stem,
                name=str(raw.get("name", yaml_file.stem)),
                version=str(raw.get("version", "")),
                type=str(raw.get("type", "unknown")),
                path=yaml_file,
                source="registry",
            )
        )
    return packs


def list_builtin_packs() -> list[InstalledPack]:
    """Return metadata for packs shipped with the package."""
    packs: list[InstalledPack] = []
    if not BUILTIN_PACKS_DIR.exists():
        return packs
    for yaml_file in sorted(BUILTIN_PACKS_DIR.glob("*.yaml")):
        raw = safe_read_yaml(yaml_file) or {}
        packs.append(
            InstalledPack(
                id=yaml_file.stem,
                name=str(raw.get("name", yaml_file.stem)),
                version=str(raw.get("version", "")),
                type=str(raw.get("type", "unknown")),
                path=yaml_file,
                source="builtin",
            )
        )
    return packs


# ── rule pack loading ─────────────────────────────────────────────────────────


def load_scan_rules_from_dirs(dirs: list[str]) -> list:
    """Load ScanRule objects from all *.yaml rule pack files in *dirs*.

    Silently skips non-existent directories and files with no ``scanner_rules``
    key (those are context/profile packs, not rule packs).

    Raises ``ValueError`` if a file *does* contain a ``scanner_rules`` key but
    the rules cannot be parsed.  Fail-closed: a malformed rule pack is never
    silently ignored — degraded scan coverage is worse than a hard error.
    """
    from promptgenie.core.config import _parse_custom_scan_rules

    rules = []
    for dir_str in dirs:
        dir_path = Path(dir_str).expanduser().resolve()
        if not dir_path.is_dir():
            continue
        for yaml_file in sorted(dir_path.glob("*.yaml")):
            try:
                raw = safe_read_yaml(yaml_file) or {}
            except Exception:
                continue  # unreadable / unparseable YAML — not a rule pack, skip silently
            raw_rules = raw.get("scanner_rules", [])
            if not raw_rules:
                continue
            # File declares scanner_rules — any further parse error is surfaced, not swallowed.
            try:
                rules.extend(_parse_custom_scan_rules(raw_rules))
            except Exception as exc:
                raise ValueError(f"Malformed scanner rule pack '{yaml_file}': {exc}") from exc
    return rules


def load_lint_rules_from_dirs(dirs: list[str]) -> list:
    """Load LintRule objects from all *.yaml rule pack files in *dirs*.

    Silently skips non-existent directories and files with no ``lint_rules``
    key.  Raises ``ValueError`` if a file declares ``lint_rules`` but they
    cannot be parsed (fail-closed — see ``load_scan_rules_from_dirs``).
    """
    from promptgenie.core.config import _parse_custom_lint_rules

    rules = []
    for dir_str in dirs:
        dir_path = Path(dir_str).expanduser().resolve()
        if not dir_path.is_dir():
            continue
        for yaml_file in sorted(dir_path.glob("*.yaml")):
            try:
                raw = safe_read_yaml(yaml_file) or {}
            except Exception:
                continue  # unreadable / unparseable YAML — not a rule pack, skip silently
            raw_rules = raw.get("lint_rules", [])
            if not raw_rules:
                continue
            try:
                rules.extend(_parse_custom_lint_rules(raw_rules))
            except Exception as exc:
                raise ValueError(f"Malformed lint rule pack '{yaml_file}': {exc}") from exc
    return rules
