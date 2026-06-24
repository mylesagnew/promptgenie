"""lockfile.py — Prompt lockfile engine for regulated environments.

A lockfile captures the content hashes of all inputs that determine a
prompt's output: template, policy, context files, pack versions, provider
model.  Running ``promptgenie lock prompt.yaml`` writes
``prompt.yaml.lock`` alongside the spec.  The ``--check`` flag verifies
no inputs have drifted without re-running the spec.

Lockfile format (YAML):
  schema_version: "1.0"
  created_at: "2026-06-11T12:00:00+00:00"
  spec: prompt.yaml
  spec_hash: sha256:…
  entries:
    - kind: template
      path: .promptgenie/templates/code-review.yaml
      hash: sha256:…
    - kind: policy
      path: .promptgenie.policy.yaml
      hash: sha256:…
    - kind: context
      path: context/api.md
      hash: sha256:…
    - kind: pack
      id: owasp-llm-top10
      version: 1.2.3
      hash: sha256:…
    - kind: provider
      name: claude
      model: claude-haiku-4-5

Public API
----------
  ``create_lockfile(spec_path, ...)``  → LockfileRecord
  ``write_lockfile(record, dest)``     → Path
  ``load_lockfile(lock_path)``         → LockfileRecord | None
  ``check_lockfile(record)``           → LockfileCheckResult
  ``LockfileRecord``                   — dataclass
  ``LockfileCheckResult``              — dataclass with .stale list
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "1.0"
LOCKFILE_SUFFIX = ".lock"


def _sha256_file(path: Path) -> str:
    """Return sha256:<hex> for a file, or sha256:missing if not found."""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return f"sha256:{digest}"
    except OSError:
        return "sha256:missing"


def _sha256_str(s: str) -> str:
    return f"sha256:{hashlib.sha256(s.encode()).hexdigest()}"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LockEntry:
    kind: str           # template | policy | context | pack | provider
    path: str = ""      # file path (relative to spec dir)
    hash: str = ""      # sha256:<hex>
    id: str = ""        # pack id or provider name
    version: str = ""
    model: str = ""


@dataclass
class LockfileRecord:
    spec: str
    spec_hash: str
    entries: list[LockEntry] = field(default_factory=list)
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "spec": self.spec,
            "spec_hash": self.spec_hash,
            "entries": [
                {k: v for k, v in {
                    "kind": e.kind,
                    "path": e.path or None,
                    "hash": e.hash or None,
                    "id": e.id or None,
                    "version": e.version or None,
                    "model": e.model or None,
                }.items() if v}
                for e in self.entries
            ],
        }


@dataclass
class LockfileCheckResult:
    passed: bool
    stale: list[str] = field(default_factory=list)      # descriptions of what changed
    missing: list[str] = field(default_factory=list)    # lock entries that are now absent


# ---------------------------------------------------------------------------
# Lockfile creation
# ---------------------------------------------------------------------------

def create_lockfile(
    spec_path: str | Path,
    *,
    extra_context_paths: list[str] | None = None,
) -> LockfileRecord:
    """Build a LockfileRecord from a PromptSpec file.

    Scans the spec for:
    - template references
    - vars_file references
    - policy file (auto-discovered)
    - context sources with file:// paths
    - provider/model from the spec or defaults
    """
    spec_path = Path(spec_path)
    spec_dir = spec_path.parent

    spec_hash = _sha256_file(spec_path)
    entries: list[LockEntry] = []

    # Parse spec for references
    try:
        raw = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except Exception:
        raw = {}

    # Template reference
    if "template" in raw:
        tmpl_path = spec_dir / raw["template"]
        entries.append(LockEntry(
            kind="template",
            path=str(raw["template"]),
            hash=_sha256_file(tmpl_path),
        ))

    # Vars file reference
    if "vars_file" in raw:
        vf = spec_dir / raw["vars_file"]
        entries.append(LockEntry(
            kind="context",
            path=str(raw["vars_file"]),
            hash=_sha256_file(vf),
        ))

    # Context sources with file paths
    for source in raw.get("context", {}).get("sources", []):
        if isinstance(source, dict):
            src_path = source.get("path") or source.get("file")
            if src_path:
                full = spec_dir / src_path
                entries.append(LockEntry(
                    kind="context",
                    path=str(src_path),
                    hash=_sha256_file(full),
                ))

    # Extra context paths passed explicitly
    for ep in (extra_context_paths or []):
        entries.append(LockEntry(
            kind="context",
            path=ep,
            hash=_sha256_file(spec_dir / ep),
        ))

    # Policy file (auto-discovered)
    _POLICY_NAMES = [".promptgenie.policy.yaml", "promptgenie.policy.yaml"]
    for pname in _POLICY_NAMES:
        pp = spec_dir / pname
        if pp.exists():
            entries.append(LockEntry(
                kind="policy",
                path=pname,
                hash=_sha256_file(pp),
            ))
            break
    else:
        # Walk up to find policy
        for parent in spec_dir.parents:
            for pname in _POLICY_NAMES:
                pp = parent / pname
                if pp.exists():
                    entries.append(LockEntry(
                        kind="policy",
                        path=str(pp),
                        hash=_sha256_file(pp),
                    ))
                    break

    # Provider / model
    provider = raw.get("provider", "")
    model = raw.get("model", "")
    if provider or model:
        entries.append(LockEntry(
            kind="provider",
            id=provider,
            model=model,
        ))

    return LockfileRecord(
        spec=str(spec_path),
        spec_hash=spec_hash,
        entries=entries,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Write / load
# ---------------------------------------------------------------------------

def write_lockfile(record: LockfileRecord, dest: Path | None = None) -> Path:
    """Write *record* to a lockfile and return its path."""
    if dest is None:
        dest = Path(record.spec).with_suffix(
            Path(record.spec).suffix + LOCKFILE_SUFFIX
        )
    dest.write_text(
        yaml.dump(record.to_dict(), default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return dest


def load_lockfile(lock_path: str | Path) -> LockfileRecord | None:
    """Load a lockfile YAML; returns None if missing or malformed."""
    path = Path(lock_path)
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    entries = [
        LockEntry(
            kind=e.get("kind", ""),
            path=e.get("path", ""),
            hash=e.get("hash", ""),
            id=e.get("id", ""),
            version=e.get("version", ""),
            model=e.get("model", ""),
        )
        for e in data.get("entries", [])
    ]
    return LockfileRecord(
        spec=data.get("spec", ""),
        spec_hash=data.get("spec_hash", ""),
        entries=entries,
        created_at=data.get("created_at", ""),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

def check_lockfile(record: LockfileRecord) -> LockfileCheckResult:
    """Verify all locked hashes still match the current files on disk."""
    stale: list[str] = []
    missing: list[str] = []

    # Check spec itself
    current_spec_hash = _sha256_file(Path(record.spec))
    if current_spec_hash != record.spec_hash:
        stale.append(f"spec {record.spec!r}: hash changed")

    for entry in record.entries:
        if entry.kind == "provider":
            continue  # provider/model is informational only
        if not entry.path or not entry.hash:
            continue
        current_hash = _sha256_file(Path(entry.path))
        if current_hash == "sha256:missing":
            missing.append(f"{entry.kind} {entry.path!r}: file missing")
        elif current_hash != entry.hash:
            stale.append(f"{entry.kind} {entry.path!r}: hash changed (file modified)")

    return LockfileCheckResult(
        passed=not stale and not missing,
        stale=stale,
        missing=missing,
    )
