"""trust.py — a trust store for PromptGenie specs (S-2).

``promptgenie run spec.yaml`` executes a spec's host-touching context sources
(``cmd``, ``file``, ``glob``, ``env``, ``url``) automatically. A cloned malicious
repo could therefore run code on first invocation. To mirror the trust gate the
VS Code extension gained in F-003, the CLI records which specs the user has
explicitly trusted, keyed by the spec's resolved absolute path *and* its content
hash — editing a trusted spec re-prompts.

Trust records live in ``~/.config/promptgenie/trust.json`` (mode 0o600, parent
dir 0o700).

Public API
----------
  is_trusted(spec_path)        → bool
  add_trust(spec_path)         → None
  revoke_trust(spec_path)      → None
  list_trusted()               → list[dict]
  spec_requires_trust(spec)    → bool
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

_TRUST_FILE = Path("~/.config/promptgenie/trust.json").expanduser()

# Context source types that touch the host and therefore require trust.
_HOST_TOUCHING_TYPES: frozenset[str] = frozenset({"cmd", "file", "glob", "env", "url"})


def _hash_path(path: Path) -> str:
    """Return the sha256 of the resolved absolute path string."""
    resolved = str(path.expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def _hash_content(path: Path) -> str:
    """Return the sha256 of the file's current bytes (empty string if unreadable)."""
    try:
        return hashlib.sha256(path.expanduser().resolve().read_bytes()).hexdigest()
    except OSError:
        return ""


def _load() -> dict[str, dict[str, Any]]:
    if not _TRUST_FILE.exists():
        return {}
    try:
        data = json.loads(_TRUST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    entries = data.get("trusted", {})
    return entries if isinstance(entries, dict) else {}


def _save(entries: dict[str, dict[str, Any]]) -> None:
    parent = _TRUST_FILE.parent
    parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(parent, 0o700)
    _TRUST_FILE.write_text(
        json.dumps({"schema_version": "1.0", "trusted": entries}, indent=2),
        encoding="utf-8",
    )
    with contextlib.suppress(OSError):
        os.chmod(_TRUST_FILE, 0o600)


def is_trusted(spec_path: Path) -> bool:
    """Return True if *spec_path* is trusted and its content is unchanged.

    Trust is invalidated if the file's content hash no longer matches the
    stored value (so editing a trusted spec forces a re-prompt).
    """
    entries = _load()
    key = _hash_path(spec_path)
    record = entries.get(key)
    if not record:
        return False
    stored_content = record.get("content_hash", "")
    return bool(stored_content) and stored_content == _hash_content(spec_path)


def add_trust(spec_path: Path) -> None:
    """Record *spec_path* as trusted (path-hash + content-hash + timestamp)."""
    entries = _load()
    resolved = str(spec_path.expanduser().resolve())
    entries[_hash_path(spec_path)] = {
        "path": resolved,
        "content_hash": _hash_content(spec_path),
        "trusted_at": time.time(),
    }
    _save(entries)


def revoke_trust(spec_path: Path) -> None:
    """Remove any trust record for *spec_path*."""
    entries = _load()
    key = _hash_path(spec_path)
    if key in entries:
        del entries[key]
        _save(entries)


def list_trusted() -> list[dict[str, Any]]:
    """Return all trust records (path, content_hash, trusted_at)."""
    return list(_load().values())


def spec_requires_trust(spec: Any) -> bool:
    """Return True if *spec* has any host-touching context source.

    A spec with only an inline prompt / vars (no context sources, or only
    ``stdin`` / ``git_diff`` / ``git_staged``) does not require trust.
    """
    sources = getattr(spec, "context", None) or []
    return any(getattr(s, "type", None) in _HOST_TOUCHING_TYPES for s in sources)
