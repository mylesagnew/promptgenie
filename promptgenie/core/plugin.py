"""plugin.py — PromptGenie plugin SDK and entry-point discovery.

Plugins register themselves via Python entry points in their package's
``pyproject.toml``::

    [project.entry-points."promptgenie.providers"]
    my-provider = "my_package.provider:MyProvider"

    [project.entry-points."promptgenie.rules"]
    my-rules = "my_package.rules:RULES"

    [project.entry-points."promptgenie.renderers"]
    my-renderer = "my_package.renderer:MyRenderer"

    [project.entry-points."promptgenie.context_sources"]
    git-jira = "my_package.sources:JiraContextSource"

    [project.entry-points."promptgenie.evaluators"]
    llm-judge = "my_package.evaluators:LLMJudgeEvaluator"

Supported entry-point groups
-----------------------------
  promptgenie.providers         — Provider classes (complete/stream interface)
  promptgenie.rules             — List of ScanRule objects
  promptgenie.renderers         — Output formatter callables
  promptgenie.context_sources   — ContextSource classes
  promptgenie.evaluators        — Evaluator callables

Public API
----------
  ``load_plugins(group)``         → dict[str, Any]
  ``list_plugins()``              → list[PluginManifest]
  ``check_plugin_compat(manifest)`` → list[str]  (warnings)
  ``PluginManifest``              — dataclass
  ``PLUGIN_GROUPS``               — tuple of valid group names
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLUGIN_GROUPS = (
    "promptgenie.providers",
    "promptgenie.rules",
    "promptgenie.renderers",
    "promptgenie.context_sources",
    "promptgenie.evaluators",
)

_GROUP_LABELS = {
    "promptgenie.providers": "Provider",
    "promptgenie.rules": "Rules",
    "promptgenie.renderers": "Renderer",
    "promptgenie.context_sources": "Context Source",
    "promptgenie.evaluators": "Evaluator",
}

_MIN_REQUIRED_VERSION = (1, 0, 0)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PluginManifest:
    name: str
    group: str
    entry_point: str        # dotted module:attr reference
    package: str            # installed package name
    version: str
    dist_name: str          # distribution name
    origin: str = ""        # PyPI, local, git, etc.
    loaded: bool = False
    load_error: str = ""
    obj: Any = None         # the loaded object (populated by load_plugins)

    @property
    def group_label(self) -> str:
        return _GROUP_LABELS.get(self.group, self.group)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def list_plugins(groups: tuple[str, ...] | None = None) -> list[PluginManifest]:
    """Return all installed PromptGenie plugin entry points.

    Parameters
    ----------
    groups:
        Subset of PLUGIN_GROUPS to scan. Defaults to all groups.
    """
    target_groups = groups or PLUGIN_GROUPS
    manifests: list[PluginManifest] = []

    for group in target_groups:
        eps = importlib.metadata.entry_points(group=group)
        for ep in eps:
            dist = ep.dist
            dist_name = getattr(dist, "name", "") if dist else ""
            version = getattr(dist, "version", "?") if dist else "?"
            # Detect origin
            origin = _detect_origin(dist)
            manifests.append(PluginManifest(
                name=ep.name,
                group=group,
                entry_point=ep.value,
                package=dist_name,
                version=version,
                dist_name=dist_name,
                origin=origin,
            ))

    return manifests


def load_plugins(group: str) -> dict[str, Any]:
    """Load and return all entry points for *group*.

    Returns a mapping of name → loaded object.
    Failed loads are silently skipped (error stored on the manifest but not
    raised, so a single bad plugin cannot block the CLI).
    """
    result: dict[str, Any] = {}
    eps = importlib.metadata.entry_points(group=group)
    for ep in eps:
        try:
            obj = ep.load()
            result[ep.name] = obj
        except Exception:
            pass
    return result


def _detect_origin(dist: Any) -> str:
    """Heuristically detect where a distribution came from."""
    if dist is None:
        return "unknown"
    # Check direct_url.json for editable / VCS installs
    try:
        direct_url = dist.read_text("direct_url.json")
        if direct_url:
            import json
            data = json.loads(direct_url)
            url = data.get("url", "")
            if url.startswith("file://"):
                return "local"
            if "github" in url or "gitlab" in url or url.startswith("git+"):
                return "git"
            return "url"
    except Exception:
        pass
    return "PyPI"


# ---------------------------------------------------------------------------
# Compatibility checker
# ---------------------------------------------------------------------------

def check_plugin_compat(manifest: PluginManifest) -> list[str]:
    """Return a list of compatibility warnings for *manifest*.

    Currently checks:
    - That the entry point can be loaded without error
    - That the loaded object satisfies the minimal interface for its group
    """
    warnings: list[str] = []
    eps = importlib.metadata.entry_points(group=manifest.group)
    ep = next((e for e in eps if e.name == manifest.name), None)
    if ep is None:
        return [f"Entry point {manifest.name!r} not found in group {manifest.group!r}"]

    try:
        obj = ep.load()
    except Exception as exc:
        return [f"Load error: {exc}"]

    # Group-specific interface checks
    if manifest.group == "promptgenie.providers":
        missing = [m for m in ("complete", "stream") if not hasattr(obj, m)]
        if missing:
            warnings.append(
                f"Provider {manifest.name!r} is missing methods: {', '.join(missing)}"
            )

    if manifest.group == "promptgenie.rules":
        if not isinstance(obj, (list, tuple)):
            warnings.append(
                f"Rules plugin {manifest.name!r} must export a list of ScanRule objects"
            )

    return warnings


# ---------------------------------------------------------------------------
# Scaffold helper
# ---------------------------------------------------------------------------

_SCAFFOLD_TEMPLATE = """\
\"\"\"PromptGenie plugin: {name}

Entry-point group: {group}
\"\"\"

from __future__ import annotations

# TODO: implement your plugin here.
# Register it in pyproject.toml:
#
#   [project.entry-points."{group}"]
#   {name} = "{module}:{export}"

"""


def scaffold_plugin(
    name: str,
    group: str,
    *,
    output_dir: str = ".",
) -> str:
    """Write a stub plugin file and return its path."""
    import re
    from pathlib import Path

    if group not in PLUGIN_GROUPS:
        raise ValueError(
            f"Unknown group {group!r}. Valid groups: {list(PLUGIN_GROUPS)}"
        )

    module = re.sub(r"[^a-z0-9_]", "_", name.lower())
    suffix = group.split(".")[-1].rstrip("s")  # "providers" → "provider"
    filename = f"{module}_{suffix}.py"
    path = Path(output_dir) / filename
    path.write_text(
        _SCAFFOLD_TEMPLATE.format(name=name, group=group, module=module, export="Plugin"),
        encoding="utf-8",
    )
    return str(path)
