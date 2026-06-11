"""fileio.py — safe file I/O helpers for PromptGenie.

All prompt and config reads are bounded to 1 MB (prompts) or 512 KB (YAML
config/data files) to prevent accidental processing of multi-gigabyte inputs.
All writes go through a tempfile-then-rename atomic pattern so a crash mid-
write never leaves a truncated output file. Encoding is always UTF-8.

Public API
----------
safe_read_text(path, max_bytes=MAX_PROMPT_BYTES)  → str
safe_read_yaml(path, max_bytes=MAX_YAML_BYTES)    → dict | list | None
safe_write_text(path, content, force=False)       → None
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------

MAX_PROMPT_BYTES: int = 1 * 1024 * 1024  # 1 MB  — prompt / response files
MAX_YAML_BYTES: int = 512 * 1024  # 512 KB — YAML config / data files


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FileTooLargeError(ValueError):
    """Raised when an input file exceeds the configured size limit."""

    def __init__(self, path: Path, size: int, limit: int) -> None:
        self.path = path
        self.size = size
        self.limit = limit
        super().__init__(
            f"{path}: file is {size:,} bytes, exceeds {limit:,}-byte limit. "
            f"Use a smaller file or split the content."
        )


class FileExistsProtectedError(FileExistsError):
    """Raised when safe_write_text would overwrite an existing file without force=True."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"{path}: file already exists. Pass --force to overwrite.")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def safe_read_text(
    path: str | Path,
    max_bytes: int = MAX_PROMPT_BYTES,
) -> str:
    """Read *path* as UTF-8 text, raising FileTooLargeError if it exceeds *max_bytes*.

    Pass ``"-"`` as *path* to read from stdin instead of a file.

    Raises
    ------
    FileTooLargeError
        If the input exceeds *max_bytes*.
    FileNotFoundError
        If the file does not exist (propagated from Path.open).
    """
    if str(path) == "-":
        raw = sys.stdin.buffer.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise FileTooLargeError(Path("<stdin>"), len(raw), max_bytes)
        return raw.decode("utf-8")
    p = Path(path)
    size = p.stat().st_size
    if size > max_bytes:
        raise FileTooLargeError(p, size, max_bytes)
    return p.read_text(encoding="utf-8")


def safe_read_yaml(
    path: str | Path,
    max_bytes: int = MAX_YAML_BYTES,
) -> Any:
    """Read *path* as a YAML document, bounded to *max_bytes*.

    Returns the parsed object (dict, list, or None for an empty file).

    Raises
    ------
    FileTooLargeError
        If the file size exceeds *max_bytes*.
    FileNotFoundError
        If the file does not exist.
    yaml.YAMLError
        If the file is not valid YAML.
    """
    text = safe_read_text(path, max_bytes=max_bytes)
    return yaml.safe_load(text)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def safe_write_text(
    path: str | Path,
    content: str,
    force: bool = False,
) -> None:
    """Write *content* to *path* atomically (tempfile + rename), UTF-8.

    The write is performed in two steps:
    1. Write to a sibling temp file in the same directory.
    2. Rename the temp file onto *path*.

    This ensures the target file is never partially written. If the process
    crashes between steps 1 and 2 the temp file is left behind (prefixed with
    ``.promptgenie_tmp_``) but the original file, if any, is untouched.

    Parameters
    ----------
    path:
        Destination file.
    content:
        UTF-8 text to write.
    force:
        If False (default) and *path* already exists, raises
        FileExistsProtectedError. Pass True to allow overwriting.

    Raises
    ------
    FileExistsProtectedError
        If *path* exists and *force* is False.
    """
    p = Path(path)
    if p.exists() and not force:
        raise FileExistsProtectedError(p)

    p.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=".promptgenie_tmp_",
        dir=p.parent,
        suffix=p.suffix,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        # atomic on POSIX; best-effort on Windows (os.replace is still safer than
        # write_text when the destination already exists)
        os.replace(tmp_path, p)
    except Exception:
        # Clean up the temp file if anything goes wrong
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
