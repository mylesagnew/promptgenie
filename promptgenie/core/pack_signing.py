"""pack_signing.py — Pack signature verification and pack diff/promote.

Signature verification
----------------------
Supports two signing backends, tried in order:
  1. minisign  (``minisign -V -p <pubkey> -m <file>``)
  2. cosign    (``cosign verify-blob --key <pubkey> --signature <sig> <file>``)

A signed pack ships with an adjacent ``<pack>.yaml.minisig`` or
``<pack>.yaml.cosig`` file.  The pack registry entry can carry::

  signature:
    method: minisign | cosign
    pubkey: <base64 or file path>
    sig_url: https://…/pack.yaml.minisig

Pack diff
---------
``diff_packs(old_path, new_path)`` compares two pack YAML files and returns
a ``PackDiff`` with added/removed/changed rule IDs and finding-count deltas.

Pack promotion
--------------
``promote_pack(name, from_env, to_env)`` copies the pack from one
registry/baseline slot to another (dev → staging → prod).

Public API
----------
  ``verify_pack_signature(pack_path, pubkey, method)``  → bool
  ``PackDiff``                                          — dataclass
  ``diff_packs(old_path, new_path)``                    → PackDiff
  ``promote_pack(name, from_env, to_env, base_dir)``    → Path
  ``run_pack_unit_test(pack_path, test_path)``          → PackTestResult
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def verify_pack_signature(
    pack_path: str | Path,
    pubkey: str,
    method: str = "minisign",
) -> bool:
    """Return True if the pack file's signature is valid.

    Parameters
    ----------
    pack_path:
        Path to the pack YAML (or tarball).
    pubkey:
        Path to a public key file, or a raw public key string.
    method:
        ``"minisign"`` or ``"cosign"``.
    """
    pack_path = Path(pack_path)
    if method == "minisign":
        sig_path = Path(str(pack_path) + ".minisig")
        if not sig_path.exists():
            raise FileNotFoundError(f"Signature file not found: {sig_path}")
        try:
            result = subprocess.run(
                ["minisign", "-V", "-p", pubkey, "-m", str(pack_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except FileNotFoundError:
            raise RuntimeError(
                "minisign not found in PATH. Install from https://jedisct1.github.io/minisign/"
            ) from None

    if method == "cosign":
        sig_path = Path(str(pack_path) + ".cosig")
        if not sig_path.exists():
            raise FileNotFoundError(f"Cosign signature not found: {sig_path}")
        try:
            result = subprocess.run(
                [
                    "cosign",
                    "verify-blob",
                    "--key",
                    pubkey,
                    "--signature",
                    str(sig_path),
                    str(pack_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except FileNotFoundError:
            raise RuntimeError(
                "cosign not found in PATH. "
                "Install from https://docs.sigstore.dev/cosign/installation/"
            ) from None

    raise ValueError(f"Unknown signing method {method!r}. Use 'minisign' or 'cosign'.")


def sign_blob_file(
    blob_path: str | Path,
    secret_key: str,
    method: str = "minisign",
) -> Path:
    """Sign *blob_path* and return the path to the detached signature file.

    Parameters
    ----------
    blob_path:
        File to sign.
    secret_key:
        Path to a minisign secret key, or a cosign key reference.
    method:
        ``"minisign"`` (writes ``<blob>.minisig``) or ``"cosign"``
        (writes ``<blob>.cosig``).
    """
    blob_path = Path(blob_path)
    if method == "minisign":
        sig_path = Path(str(blob_path) + ".minisig")
        try:
            result = subprocess.run(
                ["minisign", "-S", "-s", secret_key, "-m", str(blob_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "minisign not found in PATH. Install from https://jedisct1.github.io/minisign/"
            ) from None
        if result.returncode != 0:
            raise RuntimeError(f"minisign signing failed: {result.stderr.strip()}")
        return sig_path

    if method == "cosign":
        sig_path = Path(str(blob_path) + ".cosig")
        try:
            result = subprocess.run(
                ["cosign", "sign-blob", "--yes", "--key", secret_key,
                 "--output-signature", str(sig_path), str(blob_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "cosign not found in PATH. "
                "Install from https://docs.sigstore.dev/cosign/installation/"
            ) from None
        if result.returncode != 0:
            raise RuntimeError(f"cosign signing failed: {result.stderr.strip()}")
        return sig_path

    raise ValueError(f"Unknown signing method {method!r}. Use 'minisign' or 'cosign'.")


# ---------------------------------------------------------------------------
# Pack diff
# ---------------------------------------------------------------------------


@dataclass
class RuleDelta:
    rule_id: str
    change: str  # "added" | "removed" | "modified"
    detail: str = ""


@dataclass
class PackDiff:
    old_version: str
    new_version: str
    added_rules: list[str] = field(default_factory=list)
    removed_rules: list[str] = field(default_factory=list)
    modified_rules: list[str] = field(default_factory=list)
    pack_name_changed: bool = False
    description_changed: bool = False

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_rules
            or self.removed_rules
            or self.modified_rules
            or self.pack_name_changed
            or self.description_changed
        )

    def summary(self) -> str:
        parts = []
        if self.added_rules:
            parts.append(f"+{len(self.added_rules)} rules")
        if self.removed_rules:
            parts.append(f"-{len(self.removed_rules)} rules")
        if self.modified_rules:
            parts.append(f"~{len(self.modified_rules)} modified")
        return ", ".join(parts) if parts else "no rule changes"


def _load_pack_rules(pack_path: Path) -> dict[str, dict]:
    """Return {rule_id: rule_dict} for all rules in a pack YAML."""
    try:
        data = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    rules = {}
    for r in data.get("rules", []):
        if isinstance(r, dict) and "id" in r:
            rules[str(r["id"])] = r
    return rules


def diff_packs(old_path: str | Path, new_path: str | Path) -> PackDiff:
    """Compare two pack YAML files and return a PackDiff."""
    old_path, new_path = Path(old_path), Path(new_path)

    try:
        old_data = yaml.safe_load(old_path.read_text(encoding="utf-8")) or {}
    except Exception:
        old_data = {}
    try:
        new_data = yaml.safe_load(new_path.read_text(encoding="utf-8")) or {}
    except Exception:
        new_data = {}

    old_rules = _load_pack_rules(old_path)
    new_rules = _load_pack_rules(new_path)

    old_ids = set(old_rules)
    new_ids = set(new_rules)

    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    common = old_ids & new_ids
    modified = sorted(rid for rid in common if old_rules[rid] != new_rules[rid])

    return PackDiff(
        old_version=str(old_data.get("version", "?")),
        new_version=str(new_data.get("version", "?")),
        added_rules=added,
        removed_rules=removed,
        modified_rules=modified,
        pack_name_changed=old_data.get("name") != new_data.get("name"),
        description_changed=old_data.get("description") != new_data.get("description"),
    )


# ---------------------------------------------------------------------------
# Pack promotion
# ---------------------------------------------------------------------------


def promote_pack(
    pack_name: str,
    from_env: str,
    to_env: str,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Copy a pack from one environment slot to another.

    Environment slots live in ``<base_dir>/<env>/<pack_name>.yaml``.
    Default base_dir: ``.promptgenie/pack-envs/``
    """
    import shutil

    bdir = base_dir or (Path(".promptgenie") / "pack-envs")
    src = bdir / from_env / f"{pack_name}.yaml"
    dst_dir = bdir / to_env
    dst = dst_dir / f"{pack_name}.yaml"

    if not src.exists():
        raise FileNotFoundError(
            f"Pack {pack_name!r} not found in environment {from_env!r} at {src}"
        )
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Pack unit test
# ---------------------------------------------------------------------------


@dataclass
class PackTestCase:
    name: str
    input: str
    expected_rules: list[str] = field(default_factory=list)
    expected_count_min: int | None = None
    expected_count_max: int | None = None


@dataclass
class PackTestResult:
    passed: bool
    total: int
    pass_count: int
    fail_count: int
    cases: list[dict] = field(default_factory=list)


def run_pack_unit_test(pack_path: str | Path, test_path: str | Path) -> PackTestResult:
    """Run a pack's unit test file against the pack's rules.

    Test file format (YAML)::

        pack: path/to/pack.yaml

        cases:
          - name: detects SQL injection
            input: "SELECT * FROM users WHERE id = $1"
            expected_rules:
              - SQLI_001
          - name: no match on clean input
            input: "Hello, how can I help?"
            expected_rules: []
    """
    from promptgenie.core.config import ScannerConfig
    from promptgenie.core.scanner import ScanRule, scan

    pack_path = Path(pack_path)
    test_path = Path(test_path)

    test_data = yaml.safe_load(test_path.read_text(encoding="utf-8")) or {}
    pack_data = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}

    # Build ScanRule objects from the pack
    pack_rules = []
    for r in pack_data.get("rules", []):
        if not isinstance(r, dict):
            continue
        from promptgenie.core.scanner import coerce_confidence, coerce_finding_risk
        pack_rules.append(
            ScanRule(
                id=str(r.get("id", "PACK_RULE")),
                category=str(r.get("category", "custom")),
                pattern=str(r.get("pattern", "")),
                risk=coerce_finding_risk(str(r.get("risk", "MEDIUM"))),
                confidence=coerce_confidence(str(r.get("confidence", "MEDIUM"))),
                message=str(r.get("message", "")),
                recommendation=str(r.get("recommendation", "")),
            )
        )

    cfg = ScannerConfig(custom_scan_rules=pack_rules, enabled_rules=[r.id for r in pack_rules])
    cases_raw = test_data.get("cases", [])
    results = []
    pass_count = 0

    for raw in cases_raw:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name", "unnamed")
        input_text = str(raw.get("input", ""))
        expected_rules = [str(r) for r in raw.get("expected_rules", [])]

        scan_result = scan(input_text, config=cfg)
        found_ids = {f.code for f in scan_result.findings}

        expected_set = set(expected_rules)
        case_pass = expected_set == found_ids

        # Optional count bounds
        if raw.get("expected_count_min") is not None:
            case_pass = case_pass and len(scan_result.findings) >= raw["expected_count_min"]
        if raw.get("expected_count_max") is not None:
            case_pass = case_pass and len(scan_result.findings) <= raw["expected_count_max"]

        if case_pass:
            pass_count += 1

        results.append(
            {
                "name": name,
                "passed": case_pass,
                "expected_rules": expected_rules,
                "found_rules": sorted(found_ids),
            }
        )

    total = len(results)
    return PackTestResult(
        passed=pass_count == total,
        total=total,
        pass_count=pass_count,
        fail_count=total - pass_count,
        cases=results,
    )
