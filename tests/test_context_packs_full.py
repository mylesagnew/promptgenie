"""Extended tests for core/context_packs.py — render, inject, init (Wave 5 coverage)."""

from pathlib import Path

import pytest
import yaml

from promptgenie.core.context_packs import (
    init_pack,
    inject_pack_into_prompt,
    list_packs,
    render_pack,
)


def _write_pack(pack_id: str, data: dict) -> Path:
    """Write a pack YAML into the real packs directory and return its path."""
    from promptgenie.core.context_packs import _packs_dir

    path = _packs_dir() / f"{pack_id}.yaml"
    path.write_text(yaml.dump(data))
    return path


class TestListPacks:
    def test_returns_list(self):
        packs = list_packs()
        assert isinstance(packs, list)

    def test_builtin_packs_present(self):
        packs = list_packs()
        ids = [p["id"] for p in packs]
        assert any(ids), "Should have at least one built-in pack"

    def test_pack_entries_have_required_keys(self):
        packs = list_packs()
        for p in packs:
            assert "id" in p
            assert "name" in p
            assert "description" in p
            assert "stack" in p


class TestRenderPack:
    def test_minimal_mode_renders_stack_only(self):
        rendered = render_pack("react-supabase-app", mode="minimal")
        assert "Tech Stack" in rendered
        assert "Architecture" not in rendered

    def test_standard_mode_includes_architecture(self):
        rendered = render_pack("react-supabase-app", mode="standard")
        assert "Tech Stack" in rendered
        assert "Architecture" in rendered

    def test_exhaustive_mode_includes_all_sections(self):
        rendered = render_pack("react-supabase-app", mode="exhaustive")
        assert "Forbidden Changes" in rendered

    def test_explicit_keys_override_mode(self):
        rendered = render_pack("react-supabase-app", keys=["stack"])
        assert "Tech Stack" in rendered
        assert "Architecture" not in rendered

    def test_unknown_pack_raises(self):
        with pytest.raises(FileNotFoundError):
            render_pack("no-such-pack-xyz")


class TestInjectPack:
    def test_inject_before_scope_section(self):
        prompt = "## Objective\nDo the thing.\n\n## Scope\nOnly src/"
        result = inject_pack_into_prompt(prompt, "react-supabase-app")
        assert "Project Context" in result
        assert result.index("Project Context") < result.index("## Scope")

    def test_inject_appends_when_no_marker(self):
        prompt = "A prompt with no sections."
        result = inject_pack_into_prompt(prompt, "react-supabase-app")
        assert "Project Context" in result
        assert result.startswith("A prompt")

    def test_inject_before_constraints(self):
        prompt = "## Objective\nTask.\n\n## Constraints\nBe careful."
        result = inject_pack_into_prompt(prompt, "react-supabase-app")
        assert result.index("Project Context") < result.index("## Constraints")


class TestInitPack:
    def test_creates_yaml_file(self, tmp_path):
        # Write into an isolated dir (init_pack defaults to the user pack dir).
        path = init_pack("test-pack", name="Test Pack", description="A test pack", out_dir=tmp_path)
        assert path.exists()
        assert path.parent == tmp_path
        data = yaml.safe_load(path.read_text())
        assert data["name"] == "Test Pack"

    def test_raises_if_already_exists(self):
        # Use a known built-in pack
        with pytest.raises(FileExistsError):
            init_pack("react-supabase-app")

    def test_invalid_id_rejected(self):
        with pytest.raises(ValueError):
            init_pack("../escape")
