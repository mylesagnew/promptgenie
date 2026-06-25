"""Auto-compression of assembled context (roadmap #8).

Covers the new ``compress`` / ``compress_aggressive`` path in
``build_context``, its surfacing through the ``context build`` CLI, and the
``compress_context`` plumbing in ``run_spec``.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.context_builder import build_context
from promptgenie.core.spec import ContextSource

# Content with trailing whitespace, extra blank lines, repeated spaces, an HTML
# comment, and duplicate log lines — exercises both the safe and aggressive tiers.
_COMPRESSIBLE = (
    "# Heading   \n\n\n\nSome    prose    with    spaces.\n\n\n"
    "<!-- an html comment -->\nLINE\nLINE\nLINE\nLINE\n"
)


def _file_source(tmp_path):
    f = tmp_path / "ctx.md"
    f.write_text(_COMPRESSIBLE)
    return [ContextSource(type="file", path=str(f))]


# ── core: build_context ──────────────────────────────────────────────────────


def test_no_compression_by_default(tmp_path):
    m = build_context(_file_source(tmp_path), base_dir=tmp_path)
    assert m.compression is None


def test_compress_default_tier_reduces_tokens(tmp_path):
    m = build_context(_file_source(tmp_path), base_dir=tmp_path, compress=True)
    assert m.compression is not None
    assert m.compression.changed
    # total_tokens reflects the compressed text.
    assert m.total_tokens == m.compression.tokens_after
    assert m.total_tokens < m.compression.tokens_before
    # The safe tier must not apply aggressive techniques.
    applied = {t.name for t in m.compression.applied}
    assert "strip-html-comments" not in applied


def test_compress_aggressive_applies_more_and_saves_more(tmp_path):
    safe = build_context(_file_source(tmp_path), base_dir=tmp_path, compress=True)
    aggressive = build_context(_file_source(tmp_path), base_dir=tmp_path, compress_aggressive=True)
    applied = {t.name for t in aggressive.compression.applied}
    assert "strip-html-comments" in applied
    assert aggressive.total_tokens < safe.total_tokens


def test_compress_with_no_sources_is_noop():
    m = build_context([], compress=True)
    assert m.text == ""
    assert m.compression is None  # nothing to compress


# ── CLI: context build ───────────────────────────────────────────────────────


def test_context_build_cli_compress_json_via_stdin():
    res = CliRunner().invoke(
        cli,
        ["context", "build", "--stdin", "--compress", "--format", "json"],
        input=_COMPRESSIBLE,
    )
    assert res.exit_code in (0, 1)
    # The compression report is a diagnostic line (stderr); the JSON payload is
    # the structured stdout. Parse from the first brace to be capture-agnostic.
    data = json.loads(res.output[res.output.index("{") :])
    assert data["compression"] is not None
    assert data["compression"]["tokens_after"] <= data["compression"]["tokens_before"]
    assert data["total_tokens"] == data["compression"]["tokens_after"]


def test_context_build_cli_no_compress_has_null_compression():
    res = CliRunner().invoke(
        cli,
        ["context", "build", "--stdin", "--format", "json"],
        input=_COMPRESSIBLE,
    )
    assert res.exit_code in (0, 1)
    assert json.loads(res.output)["compression"] is None


# ── run_spec plumbing ────────────────────────────────────────────────────────


def test_run_spec_compresses_context(tmp_path):
    from promptgenie.core.run_engine import run_spec
    from promptgenie.core.spec import load_spec

    (tmp_path / "ctx.md").write_text(_COMPRESSIBLE)
    spec_path = tmp_path / "s.prompt.yaml"
    spec_path.write_text(
        "version: 1\nname: s\ntarget: claude-code\nmode: chat\n"
        "prompt: 'Review the context.'\n"
        "context:\n  - type: file\n    path: ctx.md\n"
    )
    spec = load_spec(str(spec_path))

    res = run_spec(spec, dry_run=True, no_history=True, compress_aggressive=True)
    assert res.context_manifest is not None
    assert res.context_manifest.compression is not None
    assert res.context_manifest.compression.changed


def test_run_spec_without_compress_leaves_context_untouched(tmp_path):
    from promptgenie.core.run_engine import run_spec
    from promptgenie.core.spec import load_spec

    (tmp_path / "ctx.md").write_text(_COMPRESSIBLE)
    spec_path = tmp_path / "s.prompt.yaml"
    spec_path.write_text(
        "version: 1\nname: s\ntarget: claude-code\nmode: chat\n"
        "prompt: 'Review the context.'\n"
        "context:\n  - type: file\n    path: ctx.md\n"
    )
    spec = load_spec(str(spec_path))

    res = run_spec(spec, dry_run=True, no_history=True)
    assert res.context_manifest is not None
    assert res.context_manifest.compression is None
