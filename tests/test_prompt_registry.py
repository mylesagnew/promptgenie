"""Tests for the prompt registry — store, artifact builder, signing, and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core import registry_signing
from promptgenie.core.artifact import build_artifact, materialise, push_bundle
from promptgenie.core.errors import PromptGenieError
from promptgenie.core.registry_store import (
    CONFIG_MEDIA_TYPE,
    PATH_ANNOTATION,
    Descriptor,
    LocalRegistryStore,
    Manifest,
    Reference,
    RegistryError,
    compute_digest,
)

SPEC = """\
version: 1
name: auth-review
target: claude
template: templates/review.md
provider: anthropic
model: claude-opus-4-8
context:
  - {type: file, path: ctx.md}
  - {type: glob, pattern: "src/**/*.py"}
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "review.md").write_text("# review template", encoding="utf-8")
    (tmp_path / "promptgenie.policy.yaml").write_text("rules: []", encoding="utf-8")
    (tmp_path / "ctx.md").write_text("ctx body", encoding="utf-8")
    spec = tmp_path / "auth.promptgenie.yaml"
    spec.write_text(SPEC, encoding="utf-8")
    return spec


# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------


class TestReference:
    def test_repo_and_tag(self):
        r = Reference.parse("org/auth-review:v1.2")
        assert (r.repository, r.tag, r.digest, r.host) == ("org/auth-review", "v1.2", None, None)

    def test_default_tag_latest(self):
        assert Reference.parse("auth-review").tag == "latest"

    def test_digest_pin_has_no_default_tag(self):
        r = Reference.parse("org/x@sha256:" + "a" * 64)
        assert r.tag is None and r.digest == "sha256:" + "a" * 64

    def test_host_detection(self):
        r = Reference.parse("reg.io/ns/name:t")
        assert r.host == "reg.io" and r.repository == "ns/name"

    def test_name_property(self):
        assert Reference.parse("org/sub/auth-review:v1").name == "auth-review"

    def test_str_round_trip(self):
        assert str(Reference.parse("org/x:v1")) == "org/x:v1"

    @pytest.mark.parametrize("bad", ["", "UPPER/name", "a/b@sha256:xyz", "a:bad tag!", "/leading"])
    def test_invalid(self, bad):
        with pytest.raises(RegistryError):
            Reference.parse(bad)


# ---------------------------------------------------------------------------
# Descriptor / Manifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_descriptor_round_trip(self):
        d = Descriptor("m/t", "sha256:" + "0" * 64, 12, {"k": "v"})
        assert Descriptor.from_dict(d.to_dict()) == d

    def test_manifest_round_trip(self):
        cfg = Descriptor(CONFIG_MEDIA_TYPE, "sha256:" + "1" * 64, 3)
        layer = Descriptor("m/l", "sha256:" + "2" * 64, 5, {PATH_ANNOTATION: "a.yaml"})
        m = Manifest(config=cfg, layers=[layer], annotations={"org.promptgenie.name": "x"})
        assert Manifest.from_dict(m.to_dict()).to_dict() == m.to_dict()

    def test_canonical_bytes_deterministic(self):
        cfg = Descriptor(CONFIG_MEDIA_TYPE, "sha256:" + "1" * 64, 3)
        m1 = Manifest(config=cfg, annotations={"b": "2", "a": "1"})
        m2 = Manifest(config=cfg, annotations={"a": "1", "b": "2"})
        assert m1.canonical_bytes() == m2.canonical_bytes()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class TestStore:
    def test_blob_round_trip_and_dedup(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path)
        d1 = store.put_blob(b"hello", media_type="x")
        d2 = store.put_blob(b"hello", media_type="x")
        assert d1.digest == d2.digest
        assert store.get_blob(d1.digest) == b"hello"

    def test_blob_tamper_detected(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path)
        d = store.put_blob(b"hello", media_type="x")
        store.blob_path(d.digest).write_bytes(b"tampered")
        with pytest.raises(RegistryError, match="mismatch"):
            store.get_blob(d.digest)

    def test_manifest_round_trip(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path)
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        digest = store.put_manifest(Manifest(config=cfg))
        assert store.get_manifest(digest).config.digest == cfg.digest

    def test_resolve_by_tag_and_digest(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path)
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        digest = store.put_manifest(Manifest(config=cfg))
        store.set_tag("org/x", "v1", digest)
        assert store.resolve_ref(Reference.parse("org/x:v1")) == digest
        assert store.resolve_ref(Reference.parse(f"org/x@{digest}")) == digest

    def test_resolve_unknown_repo_and_tag(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path)
        with pytest.raises(RegistryError, match="Repository not found"):
            store.resolve_ref(Reference.parse("ghost:latest"))
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        store.set_tag("org/x", "v1", store.put_manifest(Manifest(config=cfg)))
        with pytest.raises(RegistryError, match="Tag not found"):
            store.resolve_ref(Reference.parse("org/x:v9"))

    def test_remove_tag_cleans_empty_repo(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path)
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        digest = store.put_manifest(Manifest(config=cfg))
        store.set_tag("org/x", "v1", digest)
        store.remove_tag("org/x", "v1")
        assert store.list_repos() == []

    def test_gc_keeps_referenced_removes_orphans(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path)
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        layer = store.put_blob(b"layer", media_type="x")
        digest = store.put_manifest(Manifest(config=cfg, layers=[layer]))
        store.set_tag("org/x", "v1", digest)
        store.put_blob(b"orphan", media_type="x")  # unreferenced
        removed = store.gc(dry_run=True)
        assert len(removed) == 1
        store.gc()
        assert store.get_blob(layer.digest) == b"layer"  # referenced blob survives


# ---------------------------------------------------------------------------
# Artifact builder
# ---------------------------------------------------------------------------


class TestArtifact:
    def test_spec_layers_enumerated(self, tmp_path: Path):
        spec = _project(tmp_path)
        bundle = build_artifact(spec, name="org/auth-review", tag="v1")
        kinds = {layer.kind for layer in bundle.layers}
        assert kinds == {"spec", "template", "policy", "context"}
        assert bundle.config["dynamic_context"] == ["pattern:src/**/*.py"]
        assert bundle.annotations["org.promptgenie.provider"] == "anthropic"

    def test_schema_layer_included(self, tmp_path: Path):
        (tmp_path / "out.schema.json").write_text("{}", encoding="utf-8")
        spec = tmp_path / "s.promptgenie.yaml"
        spec.write_text(
            "version: 1\nname: s\ntarget: claude\noutput_contract: {schema: out.schema.json}\n",
            encoding="utf-8",
        )
        bundle = build_artifact(spec, name="s", tag="v1")
        assert any(layer.kind == "schema" for layer in bundle.layers)

    def test_markdown_prompt_single_layer(self, tmp_path: Path):
        prompt = tmp_path / "p.md"
        prompt.write_text("# prompt", encoding="utf-8")
        bundle = build_artifact(prompt, name="p", tag="v1")
        assert [layer.kind for layer in bundle.layers] == ["prompt"]

    def test_invalid_spec_raises(self, tmp_path: Path):
        spec = tmp_path / "bad.yaml"
        spec.write_text("version: 2\nname: x\n", encoding="utf-8")
        with pytest.raises(PromptGenieError):
            build_artifact(spec, name="x", tag="v1")

    def test_missing_source_raises(self, tmp_path: Path):
        with pytest.raises(PromptGenieError):
            build_artifact(tmp_path / "nope.yaml", name="x", tag="v1")

    def test_push_materialise_round_trip(self, tmp_path: Path):
        spec = _project(tmp_path)
        bundle = build_artifact(spec, name="org/auth-review", tag="v1")
        store = LocalRegistryStore(tmp_path / "store")
        digest = push_bundle(store, bundle, "org/auth-review", "v1")
        out = tmp_path / "out"
        materialise(store, store.get_manifest(digest), out)
        assert (out / "templates" / "review.md").read_text(encoding="utf-8") == "# review template"
        assert (out / "auth.promptgenie.yaml").exists()
        assert (out / "ctx.md").exists()

    def test_materialise_blocks_traversal(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path / "store")
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        evil = store.put_blob(b"x", media_type="x", annotations={PATH_ANNOTATION: "../escape"})
        with pytest.raises(RegistryError, match="rejected|escape"):
            materialise(store, Manifest(config=cfg, layers=[evil]), tmp_path / "out")

    def test_materialise_blocks_absolute(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path / "store")
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        evil = store.put_blob(b"x", media_type="x", annotations={PATH_ANNOTATION: "/etc/passwd"})
        with pytest.raises(RegistryError):
            materialise(store, Manifest(config=cfg, layers=[evil]), tmp_path / "out")


# ---------------------------------------------------------------------------
# Signing (crypto mocked)
# ---------------------------------------------------------------------------


class TestSigning:
    def _signed_store(self, tmp_path, monkeypatch) -> tuple[LocalRegistryStore, str]:
        store = LocalRegistryStore(tmp_path)
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        digest = store.put_manifest(Manifest(config=cfg))

        def fake_sign(blob_path, key, method="minisign"):
            sig = Path(str(blob_path) + (".minisig" if method == "minisign" else ".cosig"))
            sig.write_bytes(b"SIGNATURE")
            return sig

        monkeypatch.setattr(registry_signing, "sign_blob_file", fake_sign)
        registry_signing.sign_manifest(store, digest, "secret.key", method="minisign")
        return store, digest

    def test_sign_then_verify_ok(self, tmp_path: Path, monkeypatch):
        store, digest = self._signed_store(tmp_path, monkeypatch)
        assert store.has_signature(digest)
        monkeypatch.setattr(registry_signing, "verify_pack_signature", lambda *a, **k: True)
        assert registry_signing.verify_manifest(store, digest, "pub.key") is True

    def test_verify_fails_when_unsigned(self, tmp_path: Path):
        store = LocalRegistryStore(tmp_path)
        cfg = store.put_blob(b"{}", media_type=CONFIG_MEDIA_TYPE)
        digest = store.put_manifest(Manifest(config=cfg))
        assert registry_signing.verify_manifest(store, digest, "pub.key") is False

    def test_verify_fails_on_bad_signature(self, tmp_path: Path, monkeypatch):
        store, digest = self._signed_store(tmp_path, monkeypatch)
        monkeypatch.setattr(registry_signing, "verify_pack_signature", lambda *a, **k: False)
        assert registry_signing.verify_manifest(store, digest, "pub.key") is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestRegistryCommand:
    def _push(self, runner, spec: Path, store: Path, *args) -> None:
        res = runner.invoke(cli, ["registry", "push", str(spec), "--store-path", str(store), *args])
        assert res.exit_code == 0, res.output

    def test_push_pull_round_trip(self, tmp_path: Path):
        spec = _project(tmp_path)
        store = tmp_path / "store"
        runner = CliRunner()
        self._push(runner, spec, store, "--tag", "v1.2")
        out = tmp_path / "out"
        res = runner.invoke(
            cli, ["registry", "pull", "auth-review:v1.2", "--out", str(out), "--store-path", str(store)]
        )
        assert res.exit_code == 0
        assert (out / "templates" / "review.md").exists()

    def test_list_and_show(self, tmp_path: Path):
        spec = _project(tmp_path)
        store = tmp_path / "store"
        runner = CliRunner()
        self._push(runner, spec, store, "--tag", "v1")
        assert "auth-review" in runner.invoke(
            cli, ["registry", "list", "--store-path", str(store)]
        ).output
        show = runner.invoke(
            cli, ["registry", "show", "auth-review:v1", "--store-path", str(store), "--format", "json"]
        )
        data = json.loads(show.output)
        assert data["config"]["provider"] == "anthropic"
        assert len(data["manifest"]["layers"]) == 4

    def test_search(self, tmp_path: Path):
        spec = _project(tmp_path)
        store = tmp_path / "store"
        runner = CliRunner()
        self._push(runner, spec, store, "--tag", "v1")
        assert "auth-review" in runner.invoke(
            cli, ["registry", "search", "anthropic", "--store-path", str(store)]
        ).output

    def test_rm_and_prune(self, tmp_path: Path):
        spec = _project(tmp_path)
        store = tmp_path / "store"
        runner = CliRunner()
        self._push(runner, spec, store, "--tag", "v1")
        assert runner.invoke(
            cli, ["registry", "rm", "auth-review:v1", "--store-path", str(store)]
        ).exit_code == 0
        prune = runner.invoke(cli, ["registry", "prune", "--store-path", str(store), "--format", "json"])
        assert json.loads(prune.output)["removed_count"] > 0

    def test_pull_unknown_ref_exit_2(self, tmp_path: Path):
        runner = CliRunner()
        res = runner.invoke(
            cli, ["registry", "pull", "ghost:latest", "--store-path", str(tmp_path / "store")]
        )
        assert res.exit_code == 2

    def test_sign_without_key_exit_2(self, tmp_path: Path):
        spec = _project(tmp_path)
        runner = CliRunner()
        res = runner.invoke(
            cli,
            ["registry", "push", str(spec), "--tag", "v1", "--sign", "--store-path", str(tmp_path / "store")],
        )
        assert res.exit_code == 2

    def test_require_signed_without_pubkey_exit_2(self, tmp_path: Path):
        spec = _project(tmp_path)
        store = tmp_path / "store"
        runner = CliRunner()
        self._push(runner, spec, store, "--tag", "v1")
        res = runner.invoke(
            cli, ["registry", "pull", "auth-review:v1", "--require-signed", "--store-path", str(store)]
        )
        assert res.exit_code == 2

    def test_digest_pin_pull(self, tmp_path: Path):
        spec = _project(tmp_path)
        store = tmp_path / "store"
        runner = CliRunner()
        self._push(runner, spec, store, "--tag", "v1")
        show = runner.invoke(
            cli, ["registry", "show", "auth-review:v1", "--store-path", str(store), "--format", "json"]
        )
        digest = json.loads(show.output)["digest"]
        res = runner.invoke(
            cli,
            ["registry", "pull", f"auth-review@{digest}", "--out", str(tmp_path / "o"), "--store-path", str(store)],
        )
        assert res.exit_code == 0


def test_compute_digest_shape():
    assert compute_digest(b"x").startswith("sha256:")
    assert len(compute_digest(b"x").split(":")[1]) == 64
