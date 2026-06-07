"""
context_packs.py — reusable project context blocks.

A context pack is a YAML file that captures everything a model needs to know
about a project without you repeating it in every prompt:

  - stack / architecture
  - coding style and conventions
  - known pitfalls
  - forbidden changes
  - terminology
  - preferred output format

When generating a prompt, only sections relevant to the task are injected —
not the whole pack — keeping token usage low.

Pack file format (promptgenie/context-packs/<name>.yaml):

    name: react-supabase-app
    description: "React + Supabase SaaS app"
    stack:
      - React 18 + TypeScript
      - Supabase (auth, database, storage)
      - Tailwind CSS
      - Vite
    architecture:
      - SPA with React Router
      - Supabase RLS for row-level security
      - Edge functions for server-side logic
    coding_style:
      - Functional components only, no class components
      - Custom hooks for all data fetching
      - Zod for all runtime validation
    forbidden_changes:
      - Do not modify Supabase migration files directly
      - Do not add new npm packages without approval
      - Do not change the auth flow
    known_pitfalls:
      - RLS policies must be updated when adding new tables
      - Edge functions have a 50ms cold start — avoid for latency-sensitive paths
    terminology:
      workspace: "The top-level organisational unit (like a GitHub org)"
      member: "A user who belongs to a workspace"
    preferred_output_format: "TypeScript with explicit return types"
"""

import re
from pathlib import Path

from promptgenie.core.fileio import safe_read_yaml, safe_write_text

PACKS_DIR = Path(__file__).parent.parent / "context-packs"

_PACK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_pack_id(pack_id: str) -> None:
    """Reject pack IDs that could escape the packs directory."""
    if not pack_id or not _PACK_ID_RE.match(pack_id):
        raise ValueError(
            f"Invalid pack ID {pack_id!r}. Only letters, digits, hyphens, and underscores are allowed."
        )
    # Belt-and-suspenders: resolve and assert containment
    candidate = (_packs_dir() / f"{pack_id}.yaml").resolve()
    if not str(candidate).startswith(str(_packs_dir().resolve())):
        raise ValueError(f"Pack ID {pack_id!r} resolves outside the packs directory.")


# Which pack keys map to which prompt section labels
SECTION_MAP = {
    "stack": "Tech Stack",
    "architecture": "Architecture",
    "coding_style": "Coding Style",
    "forbidden_changes": "Forbidden Changes",
    "known_pitfalls": "Known Pitfalls",
    "terminology": "Terminology",
    "preferred_output_format": "Preferred Output Format",
}

# Keys always included when a pack is injected
ALWAYS_INCLUDE = {"stack", "architecture"}

# Keys included only for agentic / exhaustive prompts
AGENTIC_KEYS = {"forbidden_changes", "known_pitfalls"}


def _packs_dir() -> Path:
    PACKS_DIR.mkdir(exist_ok=True)
    return PACKS_DIR


def list_packs() -> list[dict]:
    packs = []
    for f in sorted(_packs_dir().glob("*.yaml")):
        data = safe_read_yaml(f) or {}
        packs.append(
            {
                "id": f.stem,
                "name": data.get("name", f.stem),
                "description": data.get("description", ""),
                "stack": data.get("stack", []),
            }
        )
    return packs


def _extra_context_dirs() -> list[Path]:
    """Return additional directories to search for context packs (registry installs)."""
    from promptgenie.core.registry import USER_PACKS_DIR

    dirs = []
    if USER_PACKS_DIR.exists():
        dirs.append(USER_PACKS_DIR)
    return dirs


def load_pack(pack_id: str) -> dict:
    _validate_pack_id(pack_id)
    # Search built-in packs dir first, then registry packs dirs
    search_dirs = [_packs_dir()] + _extra_context_dirs()
    for search_dir in search_dirs:
        path = search_dir / f"{pack_id}.yaml"
        if path.exists():
            data = safe_read_yaml(path) or {}
            # Only return if this is a context-type pack (or has context-like keys)
            pack_type = data.get("type", "context")
            if pack_type == "context" or not data.get("scanner_rules") and not data.get("lint_rules"):
                return data
    raise FileNotFoundError(
        f"Context pack not found: {pack_id}  (searched {', '.join(str(d) for d in search_dirs)})"
    )


def render_pack(
    pack_id: str,
    mode: str = "standard",
    keys: list[str] | None = None,
) -> str:
    """
    Render a context pack as a markdown block for injection into a prompt.

    mode:
      minimal    — stack only
      standard   — stack + architecture + coding_style + terminology
      exhaustive — all keys
    keys:
      explicit list of keys to include (overrides mode)
    """
    pack = load_pack(pack_id)

    if keys:
        include = set(keys)
    elif mode == "minimal":
        include = {"stack"}
    elif mode == "exhaustive":
        include = set(SECTION_MAP.keys())
    else:  # standard
        include = {"stack", "architecture", "coding_style", "terminology"}

    lines = [f"## Project Context — {pack.get('name', pack_id)}"]
    if pack.get("description"):
        lines.append(f"_{pack['description']}_\n")

    for key, label in SECTION_MAP.items():
        if key not in include:
            continue
        value = pack.get(key)
        if not value:
            continue

        lines.append(f"**{label}:**")

        if isinstance(value, list):
            lines.extend(f"- {item}" for item in value)
        elif isinstance(value, dict):
            lines.extend(f"- **{k}**: {v}" for k, v in value.items())
        else:
            lines.append(str(value))

        lines.append("")

    return "\n".join(lines).strip()


def inject_pack_into_prompt(prompt_text: str, pack_id: str, mode: str = "standard") -> str:
    """Insert a rendered context pack block into an existing prompt after the Objective section."""
    rendered = render_pack(pack_id, mode=mode)

    # Insert after ## Objective block if present, else append before ## Scope or at end
    import re

    insert_markers = [r"(## Scope\b)", r"(## Constraints\b)", r"(## Context\b)"]
    for marker in insert_markers:
        if re.search(marker, prompt_text, re.MULTILINE):
            return re.sub(marker, rendered + "\n\n\\1", prompt_text, count=1, flags=re.MULTILINE)

    return prompt_text.rstrip() + "\n\n" + rendered


def init_pack(pack_id: str, name: str = "", description: str = "") -> Path:
    """Create a blank context pack file with template structure."""
    _validate_pack_id(pack_id)
    path = _packs_dir() / f"{pack_id}.yaml"
    if path.exists():
        raise FileExistsError(f"Pack already exists: {path}")

    template = f"""\
name: {name or pack_id}
description: "{description}"

stack:
  - # e.g. React 18 + TypeScript
  - # e.g. PostgreSQL

architecture:
  - # e.g. REST API with JWT auth
  - # e.g. Event-driven background jobs

coding_style:
  - # e.g. Functional components only
  - # e.g. All validation via Zod

forbidden_changes:
  - # e.g. Do not modify migration files directly
  - # e.g. Do not add packages without approval

known_pitfalls:
  - # e.g. RLS policies must be updated for new tables

terminology:
  # key: "definition"

preferred_output_format: "Structured markdown with code blocks"
"""
    safe_write_text(path, template, force=False)
    return path
