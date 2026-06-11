"""context_builder.py — assemble context from multiple sources.

Supported source types
----------------------
  file        — single file path
  glob        — glob pattern (e.g. src/**/*.py)
  stdin       — read from sys.stdin
  env         — read from an environment variable
  cmd         — run a shell command and capture stdout
  git_diff    — output of ``git diff``
  git_staged  — output of ``git diff --staged``
  url         — HTTP GET (policy-gated by default)

Each gathered chunk is called a *SourceEntry*. After gathering, the builder
trims to a token budget using one of four strategies:

  newest      — newest files first (mtime)
  smallest    — shortest sources first (fewer tokens used)
  git-relevant — sources touched in recent git commits first
  manual      — preserve spec order as-is (default)

Public API
----------
  ``build_context(sources, *, max_tokens, strategy, base_dir, no_url)``
      → ContextManifest

  ``ContextManifest``
      .text       — assembled context string ready to prepend to the prompt
      .entries    — list[SourceEntry] with hash + token_estimate
      .total_tokens — estimated token count of the assembled text
"""

from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import os
import shlex
import socket
import subprocess
import sys
import urllib.request
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from promptgenie.core.errors import EXIT_PROVIDER, EXIT_USAGE, PromptGenieError

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------


class SecurityError(PromptGenieError):
    """Raised when a security policy is violated (SSRF, path-traversal, etc.)."""


# Allowed URL schemes for context sources.
# HTTP is intentionally excluded by default to prevent cleartext data leakage.
# Set allow_insecure=True in _check_url_allowed / build_context to permit http://.
_ALLOWED_CONTEXT_SCHEMES: frozenset[str] = frozenset({"https"})
_INSECURE_CONTEXT_SCHEMES: frozenset[str] = frozenset({"https", "http"})

# Private/loopback IPv4 and IPv6 networks that must never be fetched.
_PRIVATE_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def _is_private_ip(addr_str: str) -> bool:
    """Return True if *addr_str* is an IP address in any private/loopback/link-local range."""
    try:
        addr = ipaddress.ip_address(addr_str)
        return any(addr in net for net in _PRIVATE_NETS)
    except ValueError:
        return False


def _check_url_allowed(url: str, *, allow_insecure: bool = False) -> None:
    """Raise SecurityError if *url* uses a disallowed scheme or targets an internal host.

    Blocks:
      - Non-HTTPS schemes unless *allow_insecure* is True (CWE-319)
      - Loopback addresses (127.x, ::1)
      - Private/RFC-1918 ranges (10.x, 172.16-31.x, 192.168.x)
      - Link-local / APIPA (169.254.x)
      - Hostnames that DNS-resolve to any private/loopback IP (CWE-918 DNS rebinding)

    Parameters
    ----------
    url:
        The URL to validate.
    allow_insecure:
        When True, also permit ``http://`` URLs (logs a security warning).
        Default is False — only ``https://`` is allowed.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    allowed = _INSECURE_CONTEXT_SCHEMES if allow_insecure else _ALLOWED_CONTEXT_SCHEMES
    if scheme not in allowed:
        if scheme == "http" and not allow_insecure:
            raise SecurityError(
                f"Blocked plain HTTP URL {url!r}. "
                "Only https:// is permitted by default to prevent cleartext data leakage. "
                "Pass --allow-insecure-url / allow_insecure=True to override.",
                code=EXIT_USAGE,
            )
        raise SecurityError(
            f"Blocked URL scheme {scheme!r} in context source {url!r}. "
            f"Only {sorted(allowed)} are permitted. "
            "file://, ftp://, and other schemes are disallowed to prevent SSRF.",
            code=EXIT_USAGE,
        )
    if allow_insecure and scheme == "http":
        warnings.warn(
            f"SECURITY WARNING: fetching plain HTTP URL {url!r}. "
            "Data is transmitted without encryption. Use https:// in production.",
            stacklevel=3,
        )
    hostname = parsed.hostname or ""
    # Check explicit IP literal first.
    if _is_private_ip(hostname):
        raise SecurityError(
            f"Blocked internal/private IP address {hostname!r} in URL {url!r}. "
            "Fetching from internal network addresses is disallowed (SSRF prevention).",
            code=EXIT_USAGE,
        )
    # Resolve hostname to IPs and check each resolved address (DNS-rebinding defence).
    if hostname and not hostname.replace(".", "").replace(":", "").replace("[", "").replace("]", "").isdigit():
        # hostname is not a bare IP literal — resolve it
        try:
            # strip IPv6 brackets if present
            bare = hostname.strip("[]")
            addr_infos = socket.getaddrinfo(bare, None)
            for _family, _type, _proto, _canonname, sockaddr in addr_infos:
                resolved_ip = str(sockaddr[0])
                if _is_private_ip(resolved_ip):
                    raise SecurityError(
                        f"Blocked URL {url!r}: hostname {hostname!r} resolved to "
                        f"internal/private IP {resolved_ip!r}. "
                        "DNS rebinding / SSRF prevention check failed.",
                        code=EXIT_USAGE,
                    )
        except SecurityError:
            raise
        except OSError:
            # DNS resolution failed — let the request fail naturally at connect time.
            pass


# Allowlist of commands that context sources may invoke.
# Empty set = all external commands blocked by default when using the allowlist.
# Set to None to disable allowlisting (permissive — not recommended in production).
_CMD_ALLOWLIST: frozenset[str] | None = frozenset(
    {
        "git",
        "cat",
        "ls",
        "find",
        "grep",
        "echo",
        "env",
        "printenv",
        "pwd",
        "date",
        "uname",
        "wc",
        "head",
        "tail",
        "sort",
        "uniq",
        "cut",
        "tr",
        "sed",
        "awk",
        "jq",
        "python",
        "python3",
        "node",
        "npm",
        "make",
        "cargo",
        "go",
        "mvn",
        "gradle",
    }
)


def _validate_cmd_allowed(command: str) -> list[str]:
    """Parse *command* into an argv list and validate the executable is allowed.

    Returns the argv list on success.
    Raises SecurityError if the command executable is not in the allowlist.
    Using shlex.split avoids shell=True injection; the allowlist prevents
    arbitrary executables from being invoked via spec files.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise SecurityError(
            f"Invalid command syntax in spec: {command!r}: {exc}",
            code=EXIT_USAGE,
        ) from exc

    if not argv:
        raise SecurityError("Empty command in context source.", code=EXIT_USAGE)

    executable = Path(argv[0]).name  # strip any path component
    if _CMD_ALLOWLIST is not None and executable not in _CMD_ALLOWLIST:
        raise SecurityError(
            f"Command executable {executable!r} is not in the allowed command list. "
            "Add it to _CMD_ALLOWLIST in context_builder.py if it is safe to run.",
            code=EXIT_USAGE,
        )
    return argv


# ---------------------------------------------------------------------------
# Token estimator (simple whitespace-based; no tiktoken dep required)
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4  # rough heuristic


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# .promptignore support
# ---------------------------------------------------------------------------


def _load_promptignore(base_dir: Path) -> list[str]:
    ignore_file = base_dir / ".promptignore"
    if not ignore_file.exists():
        return []
    lines = ignore_file.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _is_ignored(path: Path, patterns: list[str], base_dir: Path) -> bool:
    try:
        rel = str(path.relative_to(base_dir))
    except ValueError:
        rel = str(path)
    return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat) for pat in patterns)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SourceEntry:
    label: str  # human-readable label
    source_type: str  # file | glob | stdin | env | cmd | git_diff | git_staged | url
    content: str
    path: str = ""  # file path if applicable
    sha256: str = ""  # hex digest of content
    token_estimate: int = 0
    included: bool = True  # False if trimmed by budget
    mtime: float = 0.0  # for 'newest' strategy


@dataclass
class ContextManifest:
    text: str  # assembled context text
    entries: list[SourceEntry] = field(default_factory=list)
    total_tokens: int = 0
    trimmed_count: int = 0  # number of entries excluded by budget


# ---------------------------------------------------------------------------
# Gatherers
# ---------------------------------------------------------------------------


def _gather_file(
    path_str: str, label: str, max_bytes: int, base_dir: Path, ignore_patterns: list[str]
) -> SourceEntry | None:
    p = Path(path_str)
    if not p.is_absolute():
        p = base_dir / p
    # Resolve symlinks and normalise the path before the containment check.
    try:
        resolved = p.resolve()
    except OSError:
        return None
    # Path-traversal protection: context files must reside within base_dir.
    # This prevents spec files from reading /etc/passwd, ~/.ssh/id_rsa, etc.
    try:
        resolved_base = base_dir.resolve()
        resolved.relative_to(resolved_base)
    except ValueError as exc:
        raise SecurityError(
            f"Context file {path_str!r} resolves to {resolved} which is outside "
            f"the allowed project directory {resolved_base}. "
            "Path traversal via context sources is not permitted.",
            code=EXIT_USAGE,
        ) from exc
    if not resolved.exists():
        return None
    if _is_ignored(resolved, ignore_patterns, base_dir):
        return None
    try:
        stat = resolved.stat()
        raw = resolved.read_bytes()
        if max_bytes and len(raw) > max_bytes:
            raw = raw[:max_bytes]
        content = raw.decode("utf-8", errors="replace")
        sha = hashlib.sha256(raw).hexdigest()
        lbl = label or str(
            resolved.relative_to(resolved_base)
            if resolved.is_relative_to(resolved_base)
            else resolved
        )
        return SourceEntry(
            label=lbl,
            source_type="file",
            content=content,
            path=str(resolved),
            sha256=sha,
            token_estimate=_estimate_tokens(content),
            mtime=stat.st_mtime,
        )
    except OSError:
        return None


def _gather_glob(
    pattern: str, label: str, max_bytes: int, base_dir: Path, ignore_patterns: list[str]
) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    for p in sorted(base_dir.glob(pattern)):
        if p.is_file():
            e = _gather_file(str(p), "", max_bytes, base_dir, ignore_patterns)
            if e:
                entries.append(e)
    return entries


def _gather_stdin(label: str) -> SourceEntry:
    content = sys.stdin.read()
    sha = hashlib.sha256(content.encode()).hexdigest()
    return SourceEntry(
        label=label or "<stdin>",
        source_type="stdin",
        content=content,
        sha256=sha,
        token_estimate=_estimate_tokens(content),
    )


def _gather_env(var_name: str, label: str) -> SourceEntry | None:
    value = os.environ.get(var_name)
    if value is None:
        return None
    sha = hashlib.sha256(value.encode()).hexdigest()
    return SourceEntry(
        label=label or f"env:{var_name}",
        source_type="env",
        content=value,
        sha256=sha,
        token_estimate=_estimate_tokens(value),
    )


def _gather_cmd(command: str, label: str, max_bytes: int) -> SourceEntry:
    # Validate and parse the command before execution — raises SecurityError for
    # disallowed executables or shell-injection-prone syntax.
    argv = _validate_cmd_allowed(command)
    try:
        result = subprocess.run(  # nosec B603 — shell=False, argv validated by allowlist above
            argv, shell=False, capture_output=True, text=True, timeout=30
        )
        content = result.stdout
        if max_bytes and len(content) > max_bytes:
            content = content[:max_bytes]
        sha = hashlib.sha256(content.encode()).hexdigest()
        return SourceEntry(
            label=label or f"cmd:{command[:60]}",
            source_type="cmd",
            content=content,
            sha256=sha,
            token_estimate=_estimate_tokens(content),
        )
    except subprocess.TimeoutExpired as exc:
        raise PromptGenieError(f"Command timed out: {command}", code=EXIT_PROVIDER) from exc


def _gather_git(staged: bool, label: str) -> SourceEntry:
    # git commands are hardcoded — not driven by user spec values, so no allowlist
    # check needed here. The argv is always a fixed safe invocation.
    cmd = ["git", "diff", "--staged"] if staged else ["git", "diff"]
    try:
        result = subprocess.run(  # nosec B603 — shell=False, hardcoded argv (not from spec)
            cmd, shell=False, capture_output=True, text=True, timeout=15
        )
        content = result.stdout or "(no diff)\n"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        content = "(git not available)\n"
    sha = hashlib.sha256(content.encode()).hexdigest()
    src_type = "git_staged" if staged else "git_diff"
    return SourceEntry(
        label=label or src_type,
        source_type=src_type,
        content=content,
        sha256=sha,
        token_estimate=_estimate_tokens(content),
    )


def _gather_url(
    url: str, label: str, max_bytes: int, no_url: bool, allow_insecure: bool = False
) -> SourceEntry:
    if no_url:
        raise PromptGenieError(
            f"URL context source '{url}' is blocked (policy-gated). "
            "Pass --allow-url to permit network fetches.",
            code=EXIT_USAGE,
        )
    # SSRF / scheme validation — raises SecurityError for disallowed schemes,
    # private/loopback IPs, and DNS-resolved private addresses before any
    # network connection is opened.
    _check_url_allowed(url, allow_insecure=allow_insecure)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PromptGenie/2.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310 — scheme validated above
            raw = resp.read(max_bytes or 512_000)
        content = raw.decode("utf-8", errors="replace")
        sha = hashlib.sha256(raw).hexdigest()
        return SourceEntry(
            label=label or url,
            source_type="url",
            content=content,
            sha256=sha,
            token_estimate=_estimate_tokens(content),
        )
    except SecurityError:
        raise
    except PromptGenieError:
        raise
    except Exception as exc:
        raise PromptGenieError(
            f"Failed to fetch URL context: {exc}",
            code=EXIT_PROVIDER,
        ) from exc


# ---------------------------------------------------------------------------
# Strategy sorters
# ---------------------------------------------------------------------------


def _apply_strategy(entries: list[SourceEntry], strategy: str) -> list[SourceEntry]:
    if strategy == "newest":
        return sorted(entries, key=lambda e: e.mtime, reverse=True)
    if strategy == "smallest":
        return sorted(entries, key=lambda e: e.token_estimate)
    if strategy == "git-relevant":
        # Best effort: entries from git_diff/git_staged first, then by mtime
        def _git_key(e: SourceEntry) -> tuple[int, float]:
            git_first = 0 if e.source_type in ("git_diff", "git_staged") else 1
            return (git_first, -e.mtime)

        return sorted(entries, key=_git_key)
    # manual / unknown: preserve order
    return entries


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------


def build_context(
    sources: list[Any],  # list[ContextSource] from spec.py
    *,
    max_tokens: int = 0,
    strategy: str = "manual",
    base_dir: Path | None = None,
    no_url: bool = True,
    allow_insecure_url: bool = False,
) -> ContextManifest:
    """Gather all context sources and assemble them into a ContextManifest.

    Parameters
    ----------
    sources:
        List of ContextSource objects (from promptgenie.core.spec).
    max_tokens:
        Budget ceiling. 0 = unlimited.
    strategy:
        Ordering strategy for budget trimming: newest | smallest | git-relevant | manual.
    base_dir:
        Base directory for resolving relative paths. Defaults to cwd.
    no_url:
        If True, block url-type sources unless explicitly allowed.
    allow_insecure_url:
        When True, permit plain ``http://`` URLs in context sources (logs a
        security warning). Only ``https://`` is allowed when False (default).
        Corresponds to ``--allow-insecure-url`` / ``allow_insecure: true``.
    """
    base_dir = base_dir or Path.cwd()
    ignore_patterns = _load_promptignore(base_dir)
    raw_entries: list[SourceEntry] = []

    for src in sources:
        src_type = src.type
        lbl = src.label
        mb = src.max_bytes

        if src_type == "file":
            e = _gather_file(src.path, lbl, mb, base_dir, ignore_patterns)
            if e:
                raw_entries.append(e)
        elif src_type == "glob":
            raw_entries.extend(_gather_glob(src.pattern, lbl, mb, base_dir, ignore_patterns))
        elif src_type == "stdin":
            raw_entries.append(_gather_stdin(lbl))
        elif src_type == "env":
            e = _gather_env(src.var, lbl)
            if e:
                raw_entries.append(e)
        elif src_type == "cmd":
            raw_entries.append(_gather_cmd(src.command, lbl, mb))
        elif src_type == "git_diff":
            raw_entries.append(_gather_git(staged=False, label=lbl))
        elif src_type == "git_staged":
            raw_entries.append(_gather_git(staged=True, label=lbl))
        elif src_type == "url":
            gate = src.policy_gated if hasattr(src, "policy_gated") else True
            raw_entries.append(
                _gather_url(
                    src.url,
                    lbl,
                    mb,
                    no_url=gate and no_url,
                    allow_insecure=allow_insecure_url,
                )
            )

    # Apply ordering strategy
    ordered = _apply_strategy(raw_entries, strategy)

    # Budget trimming
    final: list[SourceEntry] = []
    trimmed = 0
    used_tokens = 0
    for entry in ordered:
        if max_tokens and (used_tokens + entry.token_estimate) > max_tokens:
            entry.included = False
            trimmed += 1
        else:
            used_tokens += entry.token_estimate
            entry.included = True
            final.append(entry)

    # Re-insert excluded entries at end (for manifest visibility)
    excluded = [e for e in ordered if not e.included]
    all_entries = final + excluded

    # Assemble text
    parts: list[str] = []
    for entry in final:
        header = f"### [{entry.source_type}] {entry.label}\n"
        parts.append(header + entry.content)

    text = "\n\n".join(parts)

    return ContextManifest(
        text=text,
        entries=all_entries,
        total_tokens=_estimate_tokens(text),
        trimmed_count=trimmed,
    )
