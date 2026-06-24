"""template_store.py — Layered template resolution and management.

Resolution order (highest priority first)
------------------------------------------
1. Project-local: .promptgenie/templates/<id>.yaml
2. User-global:   ~/.config/promptgenie/templates/<id>.yaml
3. Built-in:      promptgenie/templates/<id>.yaml  (package-shipped)

Templates are YAML files containing a ``templates`` list, each item with:
  id, name, description, category, system (optional), prompt (required),
  variables (optional list of {name, description, default}).

Public API
----------
  ``resolve_template(id)``         → TemplateRecord | None
  ``list_all_templates()``         → list[TemplateRecord]
  ``render_template(record, vars)`` → str
  ``save_user_template(record)``   → Path
  ``validate_template(record)``    → list[str]  (errors)
  ``TemplateRecord``               — dataclass
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BUILTIN_DIR = Path(__file__).parent.parent / "templates"
_USER_DIR = Path("~/.config/promptgenie/templates").expanduser()
_PROJECT_DIR = Path(".promptgenie") / "templates"

TEMPLATE_SEARCH_ORDER = (_PROJECT_DIR, _USER_DIR, _BUILTIN_DIR)


@dataclass
class TemplateVariable:
    name: str
    description: str = ""
    default: str = ""
    required: bool = False


@dataclass
class TemplateRecord:
    id: str
    name: str
    description: str = ""
    category: str = ""
    system: str = ""
    prompt: str = ""
    variables: list[TemplateVariable] = field(default_factory=list)
    source_path: Path | None = None
    source_layer: str = ""      # "builtin", "user", "project"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "system": self.system,
            "prompt": self.prompt,
            "variables": [
                {
                    "name": v.name,
                    "description": v.description,
                    "default": v.default,
                    "required": v.required,
                }
                for v in self.variables
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _layer_label(path: Path) -> str:
    resolved = path.resolve()
    if str(resolved).startswith(str(_BUILTIN_DIR.resolve())):
        return "builtin"
    if str(resolved).startswith(str(_USER_DIR.resolve())):
        return "user"
    return "project"


def _load_templates_from_file(path: Path, layer: str) -> list[TemplateRecord]:
    """Load all templates from a YAML file (multi-template or single)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    records: list[TemplateRecord] = []
    raw_list = data.get("templates", [data] if "id" in data else [])
    for raw in raw_list:
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        vars_raw = raw.get("variables", [])
        variables = [
            TemplateVariable(
                name=v.get("name", ""),
                description=v.get("description", ""),
                default=v.get("default", ""),
                required=bool(v.get("required", False)),
            )
            for v in vars_raw
            if isinstance(v, dict)
        ]
        records.append(TemplateRecord(
            id=str(raw["id"]),
            name=raw.get("name", raw["id"]),
            description=raw.get("description", ""),
            category=raw.get("category", ""),
            system=raw.get("system", ""),
            prompt=raw.get("prompt", ""),
            variables=variables,
            source_path=path,
            source_layer=layer,
        ))
    return records


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def list_all_templates() -> list[TemplateRecord]:
    """Return all available templates across all layers (no duplicates — highest wins)."""
    seen: set[str] = set()
    results: list[TemplateRecord] = []
    for directory in TEMPLATE_SEARCH_ORDER:
        if not directory.exists():
            continue
        label = _layer_label(directory)
        for yaml_file in sorted(directory.glob("*.yaml")):
            for rec in _load_templates_from_file(yaml_file, label):
                if rec.id not in seen:
                    seen.add(rec.id)
                    results.append(rec)
    return results


def resolve_template(template_id: str) -> TemplateRecord | None:
    """Find a template by ID, respecting layer priority."""
    for directory in TEMPLATE_SEARCH_ORDER:
        if not directory.exists():
            continue
        label = _layer_label(directory)
        for yaml_file in directory.glob("*.yaml"):
            for rec in _load_templates_from_file(yaml_file, label):
                if rec.id == template_id:
                    return rec
    return None


def render_template(record: TemplateRecord, variables: dict[str, str] | None = None) -> str:
    """Render *record.prompt* with *variables* substituted.

    Variable syntax: ``{{variable_name}}`` or ``{{ variable_name }}``.
    """
    text = record.prompt
    vars_dict = {v.name: v.default for v in record.variables}
    if variables:
        vars_dict.update(variables)

    def _replacer(m: re.Match) -> str:
        key = m.group(1).strip()
        return vars_dict.get(key, m.group(0))  # leave unreplaced if unknown

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", _replacer, text)


def validate_template(record: TemplateRecord) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []
    if not record.id:
        errors.append("Template 'id' is required.")
    elif not re.match(r"^[a-z0-9][a-z0-9_\-]*$", record.id):
        errors.append(
            f"Template id {record.id!r} must be lowercase alphanumeric with hyphens/underscores."
        )
    if not record.name:
        errors.append("Template 'name' is required.")
    if not record.prompt:
        errors.append("Template 'prompt' is required.")
    # Check variable references in prompt are all declared
    used = set(re.findall(r"\{\{\s*(\w+)\s*\}\}", record.prompt))
    declared = {v.name for v in record.variables}
    undeclared = used - declared
    if undeclared:
        errors.append(
            f"Prompt uses undeclared variable(s): {', '.join(sorted(undeclared))}. "
            "Add them to the 'variables' list."
        )
    return errors


def save_user_template(record: TemplateRecord) -> Path:
    """Save *record* to the user template directory and return the path."""
    _USER_DIR.mkdir(parents=True, exist_ok=True)
    dest = _USER_DIR / f"{record.id}.yaml"
    data = {"templates": [record.to_dict()]}
    dest.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return dest


def save_project_template(record: TemplateRecord) -> Path:
    """Save *record* to the project template directory."""
    _PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    dest = _PROJECT_DIR / f"{record.id}.yaml"
    data = {"templates": [record.to_dict()]}
    dest.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return dest
