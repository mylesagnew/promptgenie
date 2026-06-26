"""Tests for heuristic summarisation (low-value-section removal) in the compressor."""

from __future__ import annotations

import json

from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.compressor import compress, prune_sections

# ---------------------------------------------------------------------------
# prune_sections — unconditional low-value removal (no budget)
# ---------------------------------------------------------------------------


class TestUnconditionalRemoval:
    def test_drops_low_value_section(self):
        text = (
            "# Task\n\nDo the thing.\n\n"
            "## Examples\n\nHere is an example you can ignore.\n\n"
            "## Scope\n\nStay in scope.\n"
        )
        new, dropped = prune_sections(text)
        assert "## Examples" not in new
        assert "## Task" in new or "# Task" in new
        assert "## Scope" in new
        assert [d.heading for d in dropped] == ["Examples"]
        assert dropped[0].reason == "low_value"

    def test_preamble_never_dropped(self):
        text = "Intro instructions here.\n\n## Changelog\n\n- v1\n- v2\n"
        new, dropped = prune_sections(text)
        assert "Intro instructions here." in new
        assert "## Changelog" not in new
        assert dropped[0].heading == "Changelog"

    def test_protected_section_kept_even_if_keyword_matches(self):
        # "Output format examples" contains a protected keyword (output/format) →
        # protection wins over the low-value "examples" keyword.
        text = "# A\n\nx\n\n## Output Format Examples\n\nuse json\n"
        new, dropped = prune_sections(text)
        assert "## Output Format Examples" in new
        assert dropped == []

    def test_subtree_dropped_with_descendants(self):
        text = (
            "# Main\n\nbody\n\n"
            "## Appendix\n\nintro\n\n"
            "### Appendix part 1\n\ndetail\n\n"
            "### Appendix part 2\n\nmore detail\n\n"
            "## Requirements\n\nmust do x\n"
        )
        new, dropped = prune_sections(text)
        assert "## Appendix" not in new
        assert "Appendix part 1" not in new
        assert "Appendix part 2" not in new
        assert "## Requirements" in new
        # The whole subtree is reported as a single dropped section.
        assert [d.heading for d in dropped] == ["Appendix"]

    def test_subtree_with_protected_child_is_not_dropped(self):
        text = (
            "# Main\n\nbody\n\n"
            "## Examples\n\nsome example\n\n"
            "### Required objective\n\nthis must stay\n"
        )
        new, dropped = prune_sections(text)
        assert "## Examples" in new  # protected descendant blocks the drop
        assert dropped == []

    def test_headings_inside_code_fence_ignored(self):
        text = "# Real\n\n```\n# not a heading\n## also not\n```\n\n## Examples\n\ndrop me\n"
        new, dropped = prune_sections(text)
        assert "# not a heading" in new  # fenced content preserved
        assert "## Examples" not in new
        assert [d.heading for d in dropped] == ["Examples"]

    def test_nothing_droppable_returns_unchanged(self):
        text = "# Task\n\ndo it\n\n## Scope\n\nstay here\n"
        new, dropped = prune_sections(text)
        assert new == text
        assert dropped == []


# ---------------------------------------------------------------------------
# prune_sections — budget mode
# ---------------------------------------------------------------------------


class TestBudgetMode:
    def test_budget_already_met_drops_nothing(self):
        text = "# A\n\nshort\n\n## Notes\n\nalso short\n"
        new, dropped = prune_sections(text, max_tokens=10_000)
        assert new == text
        assert dropped == []

    def test_drops_low_value_first_then_others(self):
        # Two droppable sections; a tiny budget forces both to go, low-value first.
        body = "word " * 200
        text = (
            "# Task\n\nkeep this objective.\n\n"
            f"## Examples\n\n{body}\n\n"
            f"## Background\n\n{body}\n"
        )
        new, dropped = prune_sections(text, max_tokens=20)
        reasons = {d.heading: d.reason for d in dropped}
        assert reasons.get("Examples") == "low_value"
        # Order: low-value section is dropped before the generic one.
        assert dropped[0].heading == "Examples"

    def test_protected_section_survives_tight_budget(self):
        body = "word " * 200
        text = f"# Objective\n\n{body}\n\n## Examples\n\n{body}\n"
        new, dropped = prune_sections(text, max_tokens=5)
        # Objective is protected and must remain even though the budget is impossible.
        assert "# Objective" in new
        assert all(d.heading != "Objective" for d in dropped)


# ---------------------------------------------------------------------------
# compress() integration
# ---------------------------------------------------------------------------


class TestCompressIntegration:
    def test_summarise_off_by_default(self):
        text = "# A\n\nx\n\n## Examples\n\ndrop?\n"
        result = compress(text)
        assert "## Examples" in result.compressed_text
        assert result.dropped_sections == []

    def test_summarise_flag_drops_sections(self):
        text = "# A\n\nx\n\n## Examples\n\ndrop me\n"
        result = compress(text, summarise=True)
        assert "## Examples" not in result.compressed_text
        assert [d.heading for d in result.dropped_sections] == ["Examples"]
        assert result.tokens_after < result.tokens_before

    def test_summarise_with_budget_reports_budget_met(self):
        body = "word " * 200
        text = f"# Task\n\nkeep\n\n## Examples\n\n{body}\n"
        result = compress(text, max_tokens=30, summarise=True)
        assert result.budget_met is True
        assert any(d.heading == "Examples" for d in result.dropped_sections)


# ---------------------------------------------------------------------------
# CLI — compress --summarise
# ---------------------------------------------------------------------------


class TestCompressCLISummarise:
    def test_cli_summarise_text(self, tmp_path):
        f = tmp_path / "p.md"
        f.write_text("# Task\n\ndo it\n\n## Examples\n\nlots of example text here\n")
        res = CliRunner().invoke(cli, ["compress", str(f), "--summarise"])
        assert res.exit_code == 0
        assert "## Examples" not in res.stdout

    def test_cli_summarise_json_reports_dropped(self, tmp_path):
        f = tmp_path / "p.md"
        f.write_text("# Task\n\ndo it\n\n## Changelog\n\n- v1\n- v2\n- v3\n")
        res = CliRunner().invoke(
            cli, ["compress", str(f), "--summarise", "--format", "json"]
        )
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        headings = [d["heading"] for d in data["dropped_sections"]]
        assert "Changelog" in headings
