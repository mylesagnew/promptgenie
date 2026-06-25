"""Tests for the prompt dependency graph (core + `promptgenie graph` command)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.graph import GraphError, build_graph

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SPEC_YAML = """\
version: 1
name: auth-review
target: openai-gpt
template: code-review
provider: anthropic
model: claude-sonnet-4-6
policy:
  - promptgenie.policy.yaml
context:
  - type: file
    path: src/auth.py
  - type: glob
    pattern: "src/**/*.py"
output_contract:
  format: json
  schema: ./schemas/finding.schema.json
"""

WORKFLOW_YAML = """\
name: secure-login
target: openai-gpt
steps:
  - id: inspect
    name: Inspect existing auth
    objective: Inspect
  - id: plan
    name: Propose plan
    objective: Plan
    depends_on: inspect
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Core — spec graph
# ---------------------------------------------------------------------------


class TestSpecGraph:
    def test_spec_nodes_and_edges(self, tmp_path):
        spec = _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        g = build_graph([str(spec)])
        kinds = {n.kind for n in g.nodes.values()}
        assert {"spec", "target", "template", "provider", "model", "policy", "context", "schema"} <= kinds

        spec_id = "spec:auth-review"
        assert spec_id in g.nodes
        # Spec → template / target / provider edges exist.
        edge_pairs = {(e.src, e.dst, e.label) for e in g.edges}
        assert (spec_id, "template:code-review", "template") in edge_pairs
        assert (spec_id, "target:openai-gpt", "target") in edge_pairs
        assert (spec_id, "provider:anthropic", "provider") in edge_pairs
        # Provider → model (model hangs off the provider, not the spec).
        assert ("provider:anthropic", "model:claude-sonnet-4-6", "model") in edge_pairs

    def test_two_specs_share_provider_node(self, tmp_path):
        _write(tmp_path, "a.promptgenie.yaml", SPEC_YAML)
        _write(
            tmp_path,
            "b.promptgenie.yaml",
            SPEC_YAML.replace("name: auth-review", "name: other-review"),
        )
        g = build_graph(root=str(tmp_path))
        # Shared provider/model/template/policy are de-duplicated to one node each.
        assert sum(1 for n in g.nodes.values() if n.kind == "provider") == 1
        assert sum(1 for n in g.nodes.values() if n.kind == "spec") == 2

    def test_context_sources_become_nodes(self, tmp_path):
        spec = _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        g = build_graph([str(spec)])
        ctx_labels = {n.label for n in g.nodes.values() if n.kind == "context"}
        assert any("src/auth.py" in lbl for lbl in ctx_labels)
        assert any("src/**/*.py" in lbl for lbl in ctx_labels)


# ---------------------------------------------------------------------------
# Core — workflow graph
# ---------------------------------------------------------------------------


class TestWorkflowGraph:
    def test_workflow_steps_and_depends_on(self, tmp_path):
        wf = _write(tmp_path, "login.workflow.yaml", WORKFLOW_YAML)
        g = build_graph([str(wf)])
        assert "workflow:secure-login" in g.nodes
        step_nodes = {n.id for n in g.nodes.values() if n.kind == "step"}
        assert "step:secure-login/inspect" in step_nodes
        assert "step:secure-login/plan" in step_nodes
        # depends_on becomes an inspect --> plan "then" edge.
        edge_pairs = {(e.src, e.dst, e.label) for e in g.edges}
        assert ("step:secure-login/inspect", "step:secure-login/plan", "then") in edge_pairs


# ---------------------------------------------------------------------------
# Errors & discovery
# ---------------------------------------------------------------------------


class TestBuildErrors:
    def test_unrecognised_file_raises(self, tmp_path):
        bad = _write(tmp_path, "notes.yaml", "just: some\nrandom: mapping\n")
        with pytest.raises(GraphError, match="neither a PromptSpec"):
            build_graph([str(bad)])

    def test_unreadable_file_raises(self, tmp_path):
        with pytest.raises(GraphError, match="Cannot read"):
            build_graph([str(tmp_path / "does-not-exist.yaml")])

    def test_discovery_skips_non_spec_yaml(self, tmp_path):
        _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        _write(tmp_path, "random.yaml", "foo: bar\n")
        g = build_graph(root=str(tmp_path))
        assert sum(1 for n in g.nodes.values() if n.kind == "spec") == 1


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class TestRenderers:
    def test_mermaid_output(self, tmp_path):
        spec = _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        out = build_graph([str(spec)]).to_mermaid()
        assert out.startswith("graph LR")
        assert "spec: auth-review" in out
        assert "-->" in out
        assert "classDef" in out

    def test_dot_output(self, tmp_path):
        spec = _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        out = build_graph([str(spec)]).to_dot()
        assert out.startswith("digraph promptgenie {")
        assert "rankdir=LR;" in out
        assert "->" in out
        assert out.rstrip().endswith("}")

    def test_json_output_shape(self, tmp_path):
        spec = _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        data = build_graph([str(spec)]).to_json()
        assert data["schema_version"] == "1.0"
        assert isinstance(data["nodes"], list) and data["nodes"]
        assert {"id", "kind", "label"} <= set(data["nodes"][0])
        assert all("from" in e and "to" in e for e in data["edges"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestGraphCLI:
    def test_cli_json(self, tmp_path):
        spec = _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        res = CliRunner().invoke(cli, ["graph", str(spec), "--format", "json"])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert any(n["id"] == "spec:auth-review" for n in data["nodes"])

    def test_cli_mermaid_default(self, tmp_path):
        wf = _write(tmp_path, "login.workflow.yaml", WORKFLOW_YAML)
        res = CliRunner().invoke(cli, ["graph", str(wf)])
        assert res.exit_code == 0
        assert res.stdout.startswith("graph LR")

    def test_cli_out_file(self, tmp_path):
        spec = _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        dest = tmp_path / "out" / "g.dot"
        res = CliRunner().invoke(
            cli, ["graph", str(spec), "--format", "dot", "--out", str(dest)]
        )
        assert res.exit_code == 0
        assert dest.exists()
        assert "digraph promptgenie" in dest.read_text()

    def test_cli_unrecognised_file_exits_usage(self, tmp_path):
        bad = _write(tmp_path, "x.yaml", "random: thing\n")
        res = CliRunner().invoke(cli, ["graph", str(bad)])
        assert res.exit_code != 0

    def test_cli_scan_root(self, tmp_path):
        _write(tmp_path, "auth.promptgenie.yaml", SPEC_YAML)
        res = CliRunner().invoke(cli, ["graph", "--root", str(tmp_path), "--format", "json"])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert any(n["kind"] == "spec" for n in data["nodes"])
