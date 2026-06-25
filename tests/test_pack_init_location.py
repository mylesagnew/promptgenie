"""`pack init` must not write into the installed package dir (to-do #4).

Default target is the user pack dir (~/.promptgenie/registry/packs), which
load_pack/list_packs also search; an --out-dir override is supported.
"""

from __future__ import annotations

import promptgenie.core.context_packs as cp
import promptgenie.core.registry as registry
from promptgenie.core.context_packs import init_pack, list_packs


def test_default_writes_to_user_dir_not_package(tmp_path, monkeypatch):
    user_dir = tmp_path / "user-packs"
    monkeypatch.setattr(registry, "USER_PACKS_DIR", user_dir)
    path = init_pack("mynewpack", name="Mine")
    assert path.parent == user_dir
    assert path.exists()
    # Must NOT have been written into the installed package's context-packs dir.
    assert not (cp.PACKS_DIR / "mynewpack.yaml").exists()


def test_user_pack_appears_in_list(tmp_path, monkeypatch):
    user_dir = tmp_path / "user-packs"
    monkeypatch.setattr(registry, "USER_PACKS_DIR", user_dir)
    init_pack("listme", name="List Me")
    ids = {p["id"] for p in list_packs()}
    assert "listme" in ids
    # built-ins still listed
    assert "react-supabase-app" in ids


def test_out_dir_override(tmp_path):
    path = init_pack("elsewhere", out_dir=tmp_path)
    assert path == tmp_path / "elsewhere.yaml"
    assert path.exists()


def test_refuses_builtin_id(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(registry, "USER_PACKS_DIR", tmp_path / "u")
    with pytest.raises(FileExistsError):
        init_pack("react-supabase-app")


def test_refuses_duplicate_in_user_dir(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(registry, "USER_PACKS_DIR", tmp_path / "u")
    init_pack("dup")
    with pytest.raises(FileExistsError):
        init_pack("dup")
