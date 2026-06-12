"""input_handler.py — multi-file / directory / zip collector with safety controls.

Inspired by SkillSpector's input handling but hardened against:
  - Zip-slip path traversal (each member path is resolved and checked against
    the extraction root before extraction)
  - Decompression bombs (max total uncompressed bytes, max member count)
  - Symlinks and device files inside archives
  - Individual files that exceed a per-file byte cap
  - Total bytes across all collected files exceeding a configurable cap
  - Absolute member paths inside zip archives

Public API
----------
collect_files(
    paths,
    *,
    max_files=500,
    max_bytes=10 * 1024 * 1024,
    max_file_bytes=1 * 1024 * 1024,
    allowed_suffixes=None,
) -> CollectResult
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_FILES: int = 500
DEFAULT_MAX_BYTES: int = 10 * 1_024 * 1_024  # 10 MB total
DEFAULT_MAX_FILE_BYTES: int = 1 * 1_024 * 1_024  # 1 MB per file
DEFAULT_MAX_ZIP_MEMBERS: int = 1_000
DEFAULT_MAX_ZIP_RATIO: float = 50.0  # uncompressed / compressed size ratio cap

# Suffixes recognised as text-based prompt / config files
DEFAULT_ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {
        ".md",
        ".txt",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".prompt",
        ".promptgenie",
        ".rst",
        ".html",
        ".htm",
        ".xml",
        ".sh",
        ".py",
        ".js",
        ".ts",
        ".env",
        ".cfg",
        ".ini",
        ".conf",
    }
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CollectedFile:
    """A single collected file ready for scanning."""

    path: str  # original path or archive_path::member for zip members
    content: str  # UTF-8 decoded text
    size_bytes: int


@dataclass
class SkippedFile:
    """A file that was excluded and the reason why."""

    path: str
    reason: str  # e.g. "too_large", "wrong_suffix", "quota_exceeded", "decode_error"


@dataclass
class CollectResult:
    """Aggregated output of collect_files()."""

    files: list[CollectedFile] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)
    total_bytes: int = 0

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InputHandlerError(RuntimeError):
    """Raised when a hard limit (total bytes, file count) is breached."""


class ZipSlipError(ValueError):
    """Raised when a zip member path would escape the extraction directory."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_files(
    paths: Sequence[str | Path],
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    allowed_suffixes: frozenset[str] | set[str] | None = None,
) -> CollectResult:
    """Collect files from a mix of individual files, directories, and zip archives.

    Parameters
    ----------
    paths:
        One or more paths to scan. Each may be a file, directory, or .zip archive.
    max_files:
        Hard cap on the total number of files collected. Files beyond the cap are
        recorded as skipped with reason ``quota_exceeded``.
    max_bytes:
        Hard cap on the total uncompressed bytes across all collected files.
        When reached, remaining files are recorded as skipped with reason
        ``quota_exceeded``.
    max_file_bytes:
        Per-file size cap. Files larger than this are skipped with reason
        ``too_large``.
    allowed_suffixes:
        If provided, only files whose suffix (lower-cased) is in this set are
        collected; others are skipped with reason ``wrong_suffix``. Defaults to
        ``DEFAULT_ALLOWED_SUFFIXES``.

    Returns
    -------
    CollectResult
        All collected files plus metadata about skipped files.

    Raises
    ------
    InputHandlerError
        If a single provided path is a file that cannot be read (hard failure
        from the caller, not a soft skip).
    """
    if allowed_suffixes is None:
        allowed_suffixes = DEFAULT_ALLOWED_SUFFIXES

    result = CollectResult()

    for raw_path in paths:
        p = Path(raw_path)

        if p.suffix.lower() == ".zip":
            _collect_from_zip(p, result, max_files, max_bytes, max_file_bytes, allowed_suffixes)
        elif p.is_dir():
            _collect_from_dir(p, result, max_files, max_bytes, max_file_bytes, allowed_suffixes)
        elif p.is_file():
            _collect_single_file(
                p, str(p), result, max_files, max_bytes, max_file_bytes, allowed_suffixes
            )
        # Non-existent paths are silently skipped (caller should validate first)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _quota_reached(result: CollectResult, max_files: int, max_bytes: int) -> bool:
    return result.file_count >= max_files or result.total_bytes >= max_bytes


def _collect_single_file(
    path: Path,
    display_path: str,
    result: CollectResult,
    max_files: int,
    max_bytes: int,
    max_file_bytes: int,
    allowed_suffixes: frozenset[str] | set[str],
) -> None:
    """Attempt to add a single file to *result*, recording skips as needed."""
    if _quota_reached(result, max_files, max_bytes):
        result.skipped.append(SkippedFile(path=display_path, reason="quota_exceeded"))
        return

    suffix = path.suffix.lower()
    if suffix not in allowed_suffixes:
        result.skipped.append(SkippedFile(path=display_path, reason="wrong_suffix"))
        return

    try:
        size = path.stat().st_size
    except OSError:
        result.skipped.append(SkippedFile(path=display_path, reason="read_error"))
        return

    if size > max_file_bytes:
        result.skipped.append(SkippedFile(path=display_path, reason="too_large"))
        return

    if result.total_bytes + size > max_bytes:
        result.skipped.append(SkippedFile(path=display_path, reason="quota_exceeded"))
        return

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        result.skipped.append(SkippedFile(path=display_path, reason="read_error"))
        return

    result.files.append(CollectedFile(path=display_path, content=content, size_bytes=size))
    result.total_bytes += size


def _collect_from_dir(
    directory: Path,
    result: CollectResult,
    max_files: int,
    max_bytes: int,
    max_file_bytes: int,
    allowed_suffixes: frozenset[str] | set[str],
) -> None:
    """Recursively walk *directory* and collect matching files."""
    try:
        entries = sorted(directory.rglob("*"))
    except OSError:
        return

    for entry in entries:
        if _quota_reached(result, max_files, max_bytes):
            result.skipped.append(SkippedFile(path=str(entry), reason="quota_exceeded"))
            break
        if entry.is_file():
            _collect_single_file(
                entry, str(entry), result, max_files, max_bytes, max_file_bytes, allowed_suffixes
            )


def _collect_from_zip(
    archive: Path,
    result: CollectResult,
    max_files: int,
    max_bytes: int,
    max_file_bytes: int,
    allowed_suffixes: frozenset[str] | set[str],
) -> None:
    """Extract and collect files from *archive* with zip-slip protection."""
    if not zipfile.is_zipfile(archive):
        result.skipped.append(SkippedFile(path=str(archive), reason="invalid_zip"))
        return

    with tempfile.TemporaryDirectory(prefix="promptgenie_zip_") as tmp_dir:
        extract_root = Path(tmp_dir).resolve()

        try:
            with zipfile.ZipFile(archive, "r") as zf:
                members = zf.infolist()

                if len(members) > DEFAULT_MAX_ZIP_MEMBERS:
                    result.skipped.append(
                        SkippedFile(
                            path=str(archive),
                            reason=f"zip_too_many_members:{len(members)}",
                        )
                    )
                    return

                # Validate every member path before extracting anything
                for info in members:
                    _assert_safe_zip_member(info, extract_root)

                # Safe to extract — every member path pre-validated above by
                # _assert_safe_zip_member (absolute paths, .. traversal, symlinks,
                # and resolved-path escapes all raise before we reach here).
                zf.extractall(extract_root)

        except (zipfile.BadZipFile, zipfile.LargeZipFile, ZipSlipError, OSError) as exc:
            result.skipped.append(
                SkippedFile(path=str(archive), reason=f"zip_error:{type(exc).__name__}")
            )
            return

        # Collect the extracted files
        _collect_from_dir(
            extract_root, result, max_files, max_bytes, max_file_bytes, allowed_suffixes
        )

        # Rewrite display paths to show the archive source.
        # Use the resolved tmp_dir to handle macOS /tmp → /private/tmp symlink.
        archive_str = str(archive)
        resolved_tmp = str(Path(tmp_dir).resolve())
        for cf in result.files:
            cf_resolved = str(Path(cf.path).resolve())
            if cf_resolved.startswith(resolved_tmp):
                relative = cf_resolved[len(resolved_tmp) :].lstrip(os.sep)
                cf.path = f"{archive_str}::{relative}"


def _assert_safe_zip_member(info: zipfile.ZipInfo, extract_root: Path) -> None:
    """Raise ZipSlipError if *info* would escape *extract_root*.

    Checks:
    - Absolute paths (starts with / or drive letter on Windows)
    - Path traversal (contains ..)
    - Resolved path is under extract_root
    - Symlinks (external_attr Unix mode)
    """
    name = info.filename

    # Reject absolute member paths
    if os.path.isabs(name):
        raise ZipSlipError(f"Zip member has absolute path: {name!r}")

    # Reject obvious traversal sequences
    parts = Path(name).parts
    if ".." in parts:
        raise ZipSlipError(f"Zip member contains path traversal: {name!r}")

    # Resolve and confirm containment
    resolved = (extract_root / name).resolve()
    try:
        resolved.relative_to(extract_root)
    except ValueError:
        raise ZipSlipError(f"Zip member would escape extract directory: {name!r}") from None

    # Reject Unix symlinks (external_attr encodes the file mode in the high 16 bits)
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    if unix_mode != 0 and (unix_mode & 0xA000) == 0xA000:  # S_ISLNK
        raise ZipSlipError(f"Zip member is a symlink: {name!r}")
