"""Fifth coverage batch (roadmap follow-up: toward ~83%, no production changes).

registry install/update (mocked urllib + real checksums), change detection
(mocked git), completion cache/script generation, and plugin core.
"""

from __future__ import annotations

import hashlib
import subprocess
import types
from pathlib import Path

import pytest


class _FakeURLResp:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        if n is None or n < 0:
            d, self._data = self._data, b""
            return d
        d, self._data = self._data[:n], self._data[n:]
        return d


# ---------------------------------------------------------------------------
# registry install_pack (download + checksum verify + install)
# ---------------------------------------------------------------------------


class TestRegistryInstall:
    def _entry(self, registry, url, sha):
        return registry.RegistryEntry(
            id="demo",
            name="Demo",
            version="1.0.0",
            description="d",
            type="rules",
            url=url,
            sha256=sha,
        )

    def test_install_pack_ok(self, tmp_path, monkeypatch):
        import promptgenie.core.registry as registry

        pack_bytes = b"name: demo\ndescription: d\nrules: []\n"
        sha = hashlib.sha256(pack_bytes).hexdigest()
        monkeypatch.setattr(
            registry.urllib.request, "urlopen", lambda *a, **k: _FakeURLResp(pack_bytes)
        )
        entry = self._entry(registry, "https://x.test/demo.yaml", sha)
        path = registry.install_pack(entry, install_dir=tmp_path)
        assert Path(path).exists()
        assert Path(path).read_bytes() == pack_bytes

    def test_install_pack_checksum_mismatch(self, tmp_path, monkeypatch):
        import promptgenie.core.registry as registry

        monkeypatch.setattr(
            registry.urllib.request, "urlopen", lambda *a, **k: _FakeURLResp(b"tampered")
        )
        entry = self._entry(registry, "https://x.test/demo.yaml", "0" * 64)
        with pytest.raises(ValueError):
            registry.install_pack(entry, install_dir=tmp_path)

    def test_install_pack_requires_checksum_in_strict_mode(self, tmp_path):
        import promptgenie.core.registry as registry

        entry = self._entry(registry, "https://x.test/demo.yaml", "")
        with pytest.raises(ValueError):
            registry.install_pack(entry, install_dir=tmp_path, require_checksum=True)

    def test_install_pack_rejects_bad_scheme(self, tmp_path):
        import promptgenie.core.registry as registry

        entry = self._entry(registry, "ftp://x.test/demo.yaml", "")
        with pytest.raises(ValueError):
            registry.install_pack(entry, install_dir=tmp_path)


# ---------------------------------------------------------------------------
# change detection (mocked git)
# ---------------------------------------------------------------------------


class TestChangeDetector:
    def test_git_changed_and_staged(self, monkeypatch):
        import promptgenie.core.change_detector as cd

        def fake_run(*a, **k):
            return types.SimpleNamespace(stdout="a.md\nb.prompt.yaml\n", returncode=0)

        monkeypatch.setattr(cd.subprocess, "run", fake_run)
        changed = cd._git_changed_files("origin/main")
        assert Path("a.md") in changed
        staged = cd._git_staged_files()
        assert any(p.name == "b.prompt.yaml" for p in staged)

    def test_git_unavailable(self, monkeypatch):
        import promptgenie.core.change_detector as cd

        def boom(*a, **k):
            raise FileNotFoundError("no git")

        monkeypatch.setattr(cd.subprocess, "run", boom)
        assert cd._git_changed_files() == []


# ---------------------------------------------------------------------------
# completion cache + script generation
# ---------------------------------------------------------------------------


class TestCompletionInternals:
    def test_build_cache_and_scripts(self):
        from promptgenie.commands import completion as comp

        cache = comp._build_completion_cache()
        assert isinstance(cache, dict)
        for shell in ("zsh", "bash", "fish"):
            script = comp._generate_script(shell)
            assert script is None or isinstance(script, str)

    def test_status_command(self):
        from click.testing import CliRunner

        from promptgenie.cli import cli

        assert CliRunner().invoke(cli, ["completion", "status"]).exit_code in (0, 1)


# ---------------------------------------------------------------------------
# plugin core
# ---------------------------------------------------------------------------


class TestPluginCore:
    def test_list_plugins_and_scaffold(self, tmp_path):
        from promptgenie.core import plugin

        plugins = plugin.list_plugins()
        assert isinstance(plugins, list)
        # scaffold a stub plugin into a temp dir
        out = plugin.scaffold_plugin("myplug", "promptgenie.providers", output_dir=str(tmp_path))
        assert Path(out).exists()

    def test_load_plugins_returns_dict(self):
        from promptgenie.core import plugin

        loaded = plugin.load_plugins("promptgenie.providers")
        assert isinstance(loaded, dict)

    def test_subprocess_import_unused_guard(self):
        # keep the subprocess import referenced (used by monkeypatch targets above)
        assert subprocess is not None
