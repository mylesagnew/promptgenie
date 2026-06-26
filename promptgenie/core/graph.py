"""graph.py — prompt dependency graph.

Builds a typed node/edge graph of how PromptSpecs and workflows depend on their
templates, target profiles, providers/models, policies, context sources, and
eval suites — then renders it as Mermaid, Graphviz DOT, or JSON.

Used for CI reports and as a human-readable companion to the dependency-aware
``--changed`` filtering in :mod:`promptgenie.core.change_detector`.

Public API
----------
  ``Graph``                              — node/edge container with renderers
  ``Node`` / ``Edge``                    — graph primitives
  ``build_graph(paths, root=...)``       → Graph
  ``Graph.to_mermaid()`` / ``.to_dot()`` / ``.to_json()``

Node kinds
----------
  spec · workflow · step · template · target · provider · model ·
  policy · context · eval_suite · schema
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

# Render order / styling hints for each node kind.
NODE_KINDS: tuple[str, ...] = (
    "spec",
    "workflow",
    "step",
    "template",
    "target",
    "provider",
    "model",
    "policy",
    "context",
    "eval_suite",
    "schema",
)


@dataclass(frozen=True)
class Node:
    id: str  # stable, unique: "<kind>:<key>"
    kind: str
    label: str


@dataclass(frozen=True)
class Edge:
    src: str  # Node.id
    dst: str  # Node.id
    label: str = ""


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    _edge_keys: set[tuple[str, str, str]] = field(default_factory=set, repr=False)

    # -- construction -------------------------------------------------------

    def add_node(self, kind: str, key: str, label: str | None = None) -> str:
        """Add (or look up) a node and return its id.

        Nodes are de-duplicated by ``<kind>:<key>`` so the same template or
        provider referenced by many specs becomes a single shared node.
        """
        node_id = f"{kind}:{key}"
        if node_id not in self.nodes:
            self.nodes[node_id] = Node(id=node_id, kind=kind, label=label or key)
        return node_id

    def add_edge(self, src: str, dst: str, label: str = "") -> None:
        edge_key = (src, dst, label)
        if edge_key in self._edge_keys:
            return
        self._edge_keys.add(edge_key)
        self.edges.append(Edge(src=src, dst=dst, label=label))

    # -- ordering -----------------------------------------------------------

    def ordered_nodes(self) -> list[Node]:
        """Nodes sorted by kind (canonical order) then id — stable output."""
        kind_rank = {k: i for i, k in enumerate(NODE_KINDS)}
        return sorted(
            self.nodes.values(),
            key=lambda n: (kind_rank.get(n.kind, len(NODE_KINDS)), n.id),
        )

    # -- renderers ----------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "nodes": [{"id": n.id, "kind": n.kind, "label": n.label} for n in self.ordered_nodes()],
            "edges": [
                {"from": e.src, "to": e.dst, **({"label": e.label} if e.label else {})}
                for e in self.edges
            ],
        }

    def to_mermaid(self) -> str:
        nodes = self.ordered_nodes()
        alias = {n.id: f"n{i}" for i, n in enumerate(nodes)}
        lines = ["graph LR"]
        for n in nodes:
            label = _mermaid_escape(f"{n.kind}: {n.label}")
            shape_open, shape_close = _MERMAID_SHAPES.get(n.kind, ('["', '"]'))
            lines.append(f"    {alias[n.id]}{shape_open}{label}{shape_close}")
        for e in self.edges:
            if e.src not in alias or e.dst not in alias:
                continue
            if e.label:
                lines.append(f"    {alias[e.src]} -->|{_mermaid_escape(e.label)}| {alias[e.dst]}")
            else:
                lines.append(f"    {alias[e.src]} --> {alias[e.dst]}")
        # Colour nodes by kind for readability.
        for kind, colour in _KIND_COLOURS.items():
            members = [alias[n.id] for n in nodes if n.kind == kind]
            if members:
                lines.append(f"    classDef {kind} fill:{colour},stroke:#333,color:#111;")
                lines.append(f"    class {','.join(members)} {kind};")
        return "\n".join(lines) + "\n"

    def to_dot(self) -> str:
        nodes = self.ordered_nodes()
        alias = {n.id: f"n{i}" for i, n in enumerate(nodes)}
        lines = ["digraph promptgenie {", "    rankdir=LR;", "    node [shape=box, style=rounded];"]
        for n in nodes:
            label = _dot_escape(f"{n.kind}: {n.label}")
            colour = _KIND_COLOURS.get(n.kind, "#ffffff")
            lines.append(
                f'    {alias[n.id]} [label="{label}", style="rounded,filled", '
                f'fillcolor="{colour}"];'
            )
        for e in self.edges:
            if e.src not in alias or e.dst not in alias:
                continue
            attr = f' [label="{_dot_escape(e.label)}"]' if e.label else ""
            lines.append(f"    {alias[e.src]} -> {alias[e.dst]}{attr};")
        lines.append("}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

# (open, close) Mermaid node-shape delimiters per kind.
_MERMAID_SHAPES: dict[str, tuple[str, str]] = {
    "spec": ('["', '"]'),
    "workflow": ('[["', '"]]'),
    "step": ('("', '")'),
    "provider": ('(["', '"])'),
    "model": ('(["', '"])'),
    "policy": ('{{"', '"}}'),
    "context": ('[/"', '"/]'),
    "schema": ('["', '"]'),
}

_KIND_COLOURS: dict[str, str] = {
    "spec": "#cfe8ff",
    "workflow": "#d9c9ff",
    "step": "#e8e8e8",
    "template": "#d7f5d7",
    "target": "#fff0c2",
    "provider": "#ffd9b3",
    "model": "#ffe5cc",
    "policy": "#ffd0d0",
    "context": "#d0f0f0",
    "eval_suite": "#f0d0f0",
    "schema": "#e0e0ff",
}


def _mermaid_escape(text: str) -> str:
    # Quotes and pipes break Mermaid node/edge labels; newlines too.
    return text.replace("\\", "/").replace('"', "'").replace("|", "/").replace("\n", " ").strip()


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


class GraphError(ValueError):
    """Raised when a requested graph source cannot be read or recognised."""


def _load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, yaml.YAMLError):
        return None
    return raw if isinstance(raw, dict) else None


def _is_spec(raw: dict[str, Any]) -> bool:
    return "version" in raw and bool(raw.get("name")) and bool(raw.get("target"))


def _is_workflow(raw: dict[str, Any]) -> bool:
    return isinstance(raw.get("steps"), list) and bool(raw.get("steps"))


def _context_key(src: dict[str, Any]) -> tuple[str, str]:
    """Return (label, key) for a context source mapping."""
    t = str(src.get("type", "file"))
    detail = (
        src.get("path")
        or src.get("pattern")
        or src.get("url")
        or src.get("var")
        or src.get("command")
        or src.get("label")
        or ""
    )
    label = f"{t}:{detail}" if detail else t
    return label, label


def add_spec_to_graph(graph: Graph, raw: dict[str, Any], source: Path) -> str:
    """Add a PromptSpec (raw mapping) and its dependencies to *graph*.

    Returns the spec node id.
    """
    name = str(raw.get("name") or source.stem)
    spec_id = graph.add_node("spec", name)

    target = raw.get("target")
    if target:
        graph.add_edge(spec_id, graph.add_node("target", str(target)), "target")

    template = raw.get("template")
    if template:
        graph.add_edge(spec_id, graph.add_node("template", str(template)), "template")

    provider = raw.get("provider")
    model = raw.get("model")
    if provider:
        prov_id = graph.add_node("provider", str(provider))
        graph.add_edge(spec_id, prov_id, "provider")
        if model:
            graph.add_edge(prov_id, graph.add_node("model", str(model)), "model")
    elif model:
        graph.add_edge(spec_id, graph.add_node("model", str(model)), "model")

    for pol in raw.get("policy") or []:
        graph.add_edge(spec_id, graph.add_node("policy", str(pol)), "policy")

    for src in raw.get("context") or []:
        if isinstance(src, dict):
            label, key = _context_key(src)
            graph.add_edge(spec_id, graph.add_node("context", key, label), "context")

    oc = raw.get("output_contract") or {}
    schema = oc.get("schema") if isinstance(oc, dict) else None
    if isinstance(schema, str) and schema:
        graph.add_edge(spec_id, graph.add_node("schema", schema), "schema")

    return spec_id


def add_workflow_to_graph(graph: Graph, raw: dict[str, Any], source: Path) -> str:
    """Add a workflow and its steps (with depends_on edges) to *graph*."""
    name = str(raw.get("name") or source.stem)
    wf_id = graph.add_node("workflow", name)

    target = raw.get("target")
    if target:
        graph.add_edge(wf_id, graph.add_node("target", str(target)), "target")

    steps = raw.get("steps") or []
    for s in steps:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        sid = str(s["id"])
        step_node = graph.add_node("step", f"{name}/{sid}", s.get("name") or sid)
        graph.add_edge(wf_id, step_node, "step")
        dep = s.get("depends_on")
        if dep:
            dep_node = graph.add_node("step", f"{name}/{dep}", str(dep))
            graph.add_edge(dep_node, step_node, "then")
    return wf_id


def _discover_files(root: Path) -> list[Path]:
    files = sorted(set(root.rglob("*.yaml")) | set(root.rglob("*.yml")))
    # Skip obvious non-spec locations.
    skip_parts = {".git", "node_modules", ".venv", "__pycache__"}
    return [f for f in files if not (skip_parts & set(f.parts))]


def build_graph(paths: list[str] | None = None, root: str | Path = ".") -> Graph:
    """Build a dependency graph.

    Parameters
    ----------
    paths:
        Explicit spec/workflow files to graph. When ``None`` or empty, every
        recognisable spec/workflow under *root* is discovered and graphed.
    root:
        Directory to scan when *paths* is empty.

    Raises
    ------
    GraphError
        If an explicit path cannot be read or is neither a spec nor a workflow.
    """
    graph = Graph()

    if paths:
        for p in paths:
            path = Path(p)
            raw = _load_yaml(path)
            if raw is None:
                raise GraphError(f"Cannot read or parse {p!r} as a YAML mapping.")
            if _is_workflow(raw):
                add_workflow_to_graph(graph, raw, path)
            elif _is_spec(raw):
                add_spec_to_graph(graph, raw, path)
            else:
                raise GraphError(
                    f"{p!r} is neither a PromptSpec (version/name/target) nor a workflow (steps)."
                )
        return graph

    for path in _discover_files(Path(root)):
        raw = _load_yaml(path)
        if raw is None:
            continue
        if _is_workflow(raw):
            add_workflow_to_graph(graph, raw, path)
        elif _is_spec(raw):
            add_spec_to_graph(graph, raw, path)
    return graph
