#!/usr/bin/env python3
"""check_version_drift.py — fail if version strings disagree across the repo.

Keeps these in sync (the drift that shipped a `SECURITY.md` advertising an old
release while the package had moved on):

  * pyproject.toml          [project] version
  * CHANGELOG.md            first released heading  "## [X.Y.Z]"  (skips Unreleased)
  * SECURITY.md             "Current release: **X.Y.Z**"

Exits 0 when all three agree, 1 otherwise. Intended for CI and local use.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str | None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data.get("project", {}).get("version")


def _changelog_version() -> str | None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # First "## [X.Y.Z]" heading that is not [Unreleased].
    for m in re.finditer(r"^##\s*\[([^\]]+)\]", text, re.MULTILINE):
        tag = m.group(1).strip()
        if re.fullmatch(r"\d+\.\d+\.\d+", tag):
            return tag
    return None


def _security_version() -> str | None:
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    m = re.search(r"Current release:\s*\*\*(\d+\.\d+\.\d+)\*\*", text)
    return m.group(1) if m else None


def main() -> int:
    versions = {
        "pyproject.toml": _pyproject_version(),
        "CHANGELOG.md (latest released)": _changelog_version(),
        "SECURITY.md (current release)": _security_version(),
    }
    for source, value in versions.items():
        if not value:
            print(f"ERROR: could not determine version from {source}", file=sys.stderr)
            return 1

    distinct = set(versions.values())
    if len(distinct) != 1:
        print("ERROR: version drift detected across documentation:", file=sys.stderr)
        for source, value in versions.items():
            print(f"  {source}: {value}", file=sys.stderr)
        return 1

    print(f"Version consistency OK: {distinct.pop()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
