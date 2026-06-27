"""registry_auth.py — bearer-token credentials for remote registries.

Phase B.1 authentication: a per-host bearer token used as
``Authorization: Bearer <token>`` against an OCI registry. Tokens are resolved
in priority order:

1. ``PROMPTGENIE_REGISTRY_TOKEN`` environment variable (CI-friendly, host-agnostic);
2. the system keyring (when ``promptgenie[secrets]`` is installed), keyed
   ``registry:<host>``;
3. a ``0600`` JSON file at ``~/.config/promptgenie/registry-auth.json``
   (fallback when no keyring is available — same model as ``docker login``).

Tokens are never logged and are redacted in audit events. SSO/OIDC device-flow
login (Phase B.2) will plug in here as an additional token source.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
from pathlib import Path

ENV_TOKEN = "PROMPTGENIE_REGISTRY_TOKEN"
_AUTH_FILE = Path.home() / ".config" / "promptgenie" / "registry-auth.json"
_KEY_PREFIX = "registry:"


def _keyring():
    try:
        import keyring  # type: ignore[import-untyped]

        keyring.get_keyring()
        return keyring
    except Exception:
        return None


def normalize_host(host: str) -> str:
    """Strip scheme and any path/namespace, lowercasing the bare host."""
    h = host.strip().lower()
    for prefix in ("https://", "http://"):
        if h.startswith(prefix):
            h = h[len(prefix) :]
    return h.split("/", 1)[0]


def _read_file() -> dict[str, str]:
    if not _AUTH_FILE.exists():
        return {}
    try:
        data = json.loads(_AUTH_FILE.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_file(tokens: dict[str, str]) -> None:
    _AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _AUTH_FILE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):  # platform without chmod semantics
        _AUTH_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def store_token(host: str, token: str) -> str:
    """Persist *token* for *host*. Returns where it was stored ('keyring'|'file')."""
    host = normalize_host(host)
    kr = _keyring()
    if kr is not None:
        kr.set_password("promptgenie", _KEY_PREFIX + host, token)
        return "keyring"
    tokens = _read_file()
    tokens[host] = token
    _write_file(tokens)
    return "file"


def get_token(host: str) -> str | None:
    """Resolve a token for *host*: env var → keyring → file."""
    env = os.environ.get(ENV_TOKEN)
    if env:
        return env
    host = normalize_host(host)
    kr = _keyring()
    if kr is not None:
        val = kr.get_password("promptgenie", _KEY_PREFIX + host)
        if val:
            return str(val)
    return _read_file().get(host)


def delete_token(host: str) -> bool:
    """Remove a stored token for *host*. Returns True if something was removed."""
    host = normalize_host(host)
    removed = False
    kr = _keyring()
    if kr is not None:
        try:
            if kr.get_password("promptgenie", _KEY_PREFIX + host):
                kr.delete_password("promptgenie", _KEY_PREFIX + host)
                removed = True
        except Exception:  # pragma: no cover - backend quirks
            pass
    tokens = _read_file()
    if host in tokens:
        del tokens[host]
        _write_file(tokens)
        removed = True
    return removed
