"""Tests for the remote (OCI) registry backend — Phase B.1.

A fake OCI registry is built on httpx's in-process ``MockTransport`` (no network,
no respx dependency), exercising push/pull round-trips, blob dedup, the
untrusted-server digest-verification guard, auth token resolution, and the
air-gap gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from promptgenie.core import registry_auth, registry_backend, registry_signing
from promptgenie.core.artifact import build_artifact, materialise, push_bundle
from promptgenie.core.registry_remote import RemoteRegistryStore
from promptgenie.core.registry_store import Manifest, Reference, RegistryError, compute_digest

SPEC = """\
version: 1
name: auth-review
target: claude
template: templates/review.md
provider: anthropic
context:
  - {type: file, path: ctx.md}
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "review.md").write_text("# review", encoding="utf-8")
    (tmp_path / "ctx.md").write_text("ctx", encoding="utf-8")
    spec = tmp_path / "auth.promptgenie.yaml"
    spec.write_text(SPEC, encoding="utf-8")
    return spec


class FakeOCIRegistry:
    """Minimal in-memory OCI distribution server for MockTransport."""

    def __init__(self, *, corrupt_blobs: bool = False):
        self.blobs: dict[str, bytes] = {}
        self.manifests: dict[tuple[str, str], bytes] = {}  # (repo, reference) -> bytes
        self.upload_post_count = 0
        self.corrupt_blobs = corrupt_blobs

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        parts = path.strip("/").split("/")  # ["v2", <repo...>, kind, ref]

        if path == "/v2/" or path == "/v2":
            return httpx.Response(200, json={})

        kind = parts[-2] if len(parts) >= 2 else ""
        ref = parts[-1]
        repo = "/".join(parts[1:-2]) if len(parts) >= 4 else (parts[1] if len(parts) > 2 else "")

        # blob upload: POST /v2/<repo>/blobs/uploads/
        if method == "POST" and path.endswith("/blobs/uploads/"):
            self.upload_post_count += 1
            repo = path[len("/v2/") : -len("/blobs/uploads/")]
            return httpx.Response(202, headers={"Location": f"/v2/{repo}/blobs/uploads/u1"})

        # blob upload PUT: /v2/<repo>/blobs/uploads/<id>?digest=...
        if method == "PUT" and "/blobs/uploads/" in path:
            digest = request.url.params.get("digest", "")
            self.blobs[digest] = request.content
            return httpx.Response(201)

        # blob HEAD / GET
        if "/blobs/" in path and kind == "blobs":
            digest = ref
            if digest not in self.blobs:
                return httpx.Response(404)
            if method == "HEAD":
                return httpx.Response(200)
            body = self.blobs[digest]
            if self.corrupt_blobs:
                body = body + b"X"  # malicious server tampers with content
            return httpx.Response(200, content=body)

        # manifests PUT / GET
        if kind == "manifests":
            if method == "PUT":
                body = request.content
                self.manifests[(repo, ref)] = body
                self.manifests[(repo, compute_digest(body))] = body
                return httpx.Response(201, headers={"Docker-Content-Digest": compute_digest(body)})
            if method == "GET":
                body = self.manifests.get((repo, ref))
                if body is None:
                    return httpx.Response(404)
                return httpx.Response(200, content=body)

        # tags list
        if path.endswith("/tags/list"):
            repo = path[len("/v2/") : -len("/tags/list")]
            tags = [r for (rp, r) in self.manifests if rp == repo and not r.startswith("sha256:")]
            return httpx.Response(200, json={"name": repo, "tags": sorted(set(tags))})

        return httpx.Response(404)


def _remote(reg: FakeOCIRegistry, repository: str, **kw) -> RemoteRegistryStore:
    client = httpx.Client(transport=httpx.MockTransport(reg.handler), base_url="https://reg.test")
    return RemoteRegistryStore("https://reg.test", repository, client=client, **kw)


# ---------------------------------------------------------------------------
# Push / pull round trip
# ---------------------------------------------------------------------------


class TestRemoteRoundTrip:
    def test_push_then_pull(self, tmp_path: Path):
        reg = FakeOCIRegistry()
        store = _remote(reg, "myorg/auth-review")
        bundle = build_artifact(_project(tmp_path), name="myorg/auth-review", tag="v1")
        digest = push_bundle(store, bundle, "myorg/auth-review", "v1")

        assert store.resolve_ref(Reference.parse("myorg/auth-review:v1")) == digest
        manifest = store.get_manifest(digest)
        out = tmp_path / "out"
        materialise(store, manifest, out)
        assert (out / "templates" / "review.md").read_text(encoding="utf-8") == "# review"
        assert (out / "auth.promptgenie.yaml").exists()

    def test_blob_dedup_on_push(self, tmp_path: Path):
        reg = FakeOCIRegistry()
        store = _remote(reg, "myorg/x")
        store.put_blob(b"same", media_type="x")
        before = reg.upload_post_count
        store.put_blob(b"same", media_type="x")  # already present → no new upload
        assert reg.upload_post_count == before

    def test_tags_list(self, tmp_path: Path):
        reg = FakeOCIRegistry()
        store = _remote(reg, "myorg/x")
        bundle = build_artifact(_project(tmp_path), name="myorg/x", tag="v1")
        push_bundle(store, bundle, "myorg/x", "v1")
        tags = [t.tag for t in store.list_tags("myorg/x")]
        assert "v1" in tags


# ---------------------------------------------------------------------------
# Untrusted server — digest verification is fail-closed
# ---------------------------------------------------------------------------


class TestUntrustedServer:
    def test_tampered_blob_rejected(self, tmp_path: Path):
        reg = FakeOCIRegistry(corrupt_blobs=True)
        store = _remote(reg, "myorg/x")
        desc = store.put_blob(b"trusted", media_type="x")
        with pytest.raises(RegistryError, match="mismatch"):
            store.get_blob(desc.digest)

    def test_require_https(self):
        with pytest.raises(RegistryError, match="HTTPS"):
            RemoteRegistryStore("http://reg.test", "x")

    def test_insecure_allows_http(self):
        # Should construct without raising when insecure is set.
        store = RemoteRegistryStore("http://reg.test", "x", insecure=True, client=object())
        assert store.repository == "x"


# ---------------------------------------------------------------------------
# Remote signing (cosign-style .sig tag)
# ---------------------------------------------------------------------------


class TestRemoteSigning:
    def test_sign_then_find(self, tmp_path: Path, monkeypatch):
        reg = FakeOCIRegistry()
        store = _remote(reg, "myorg/x")
        bundle = build_artifact(_project(tmp_path), name="myorg/x", tag="v1")
        digest = push_bundle(store, bundle, "myorg/x", "v1")

        def fake_sign(blob_path, key, method="minisign"):
            sig = Path(str(blob_path) + ".minisig")
            sig.write_bytes(b"SIG")
            return sig

        monkeypatch.setattr(registry_signing, "sign_blob_file", fake_sign)
        registry_signing.sign_manifest(store, digest, "k", method="minisign")
        assert store.has_signature(digest)
        found = store.find_signature(digest)
        assert found is not None and found[0] == "minisign" and found[1] == b"SIG"


# ---------------------------------------------------------------------------
# Backend resolution + air-gap
# ---------------------------------------------------------------------------


class TestBackendResolution:
    def test_parse_remote(self):
        assert registry_backend.parse_remote("ghcr.io") == ("ghcr.io", "")
        assert registry_backend.parse_remote("ghcr.io/myorg") == ("ghcr.io", "myorg")
        assert registry_backend.parse_remote("https://reg.io/a/b") == ("https://reg.io", "a/b")

    def test_local_when_no_remote(self, tmp_path: Path):
        store, repo = registry_backend.resolve_push_target(
            None, "auth-review", store_path=str(tmp_path)
        )
        assert repo == "auth-review"
        assert not registry_backend.is_remote(store)

    def test_remote_namespace_prefixed(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(registry_backend, "_airgap_blocked", lambda: False)
        monkeypatch.setattr(registry_auth, "get_token", lambda host: None)
        store, repo = registry_backend.resolve_push_target(
            "ghcr.io/myorg", "auth-review", store_path=None
        )
        assert repo == "myorg/auth-review"
        assert registry_backend.is_remote(store)

    def test_airgap_blocks_remote(self, monkeypatch):
        monkeypatch.setattr(registry_backend, "_airgap_blocked", lambda: True)
        with pytest.raises(RegistryError, match="Air-gap"):
            registry_backend.resolve_push_target("ghcr.io", "x", store_path=None)

    def test_ref_with_host_selects_remote(self, monkeypatch):
        monkeypatch.setattr(registry_backend, "_airgap_blocked", lambda: False)
        monkeypatch.setattr(registry_auth, "get_token", lambda host: None)
        store, ref = registry_backend.resolve_ref_target(
            Reference.parse("ghcr.io/myorg/x:v1"), None, store_path=None
        )
        assert registry_backend.is_remote(store) and ref.repository == "myorg/x"


# ---------------------------------------------------------------------------
# Token auth (file fallback; no keyring)
# ---------------------------------------------------------------------------


class TestAuth:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(registry_auth, "_keyring", lambda: None)
        monkeypatch.setattr(registry_auth, "_AUTH_FILE", tmp_path / "auth.json")
        monkeypatch.delenv(registry_auth.ENV_TOKEN, raising=False)

    def test_store_get_delete(self):
        assert registry_auth.get_token("ghcr.io") is None
        assert registry_auth.store_token("ghcr.io", "tok123") == "file"
        assert registry_auth.get_token("ghcr.io") == "tok123"
        assert registry_auth.delete_token("ghcr.io") is True
        assert registry_auth.get_token("ghcr.io") is None

    def test_env_overrides(self, monkeypatch):
        registry_auth.store_token("ghcr.io", "filetok")
        monkeypatch.setenv(registry_auth.ENV_TOKEN, "envtok")
        assert registry_auth.get_token("ghcr.io") == "envtok"

    def test_normalize_host(self):
        assert registry_auth.normalize_host("https://ghcr.io/myorg") == "ghcr.io"
        assert registry_auth.normalize_host("GHCR.IO") == "ghcr.io"


# ---------------------------------------------------------------------------
# CLI login / logout
# ---------------------------------------------------------------------------


class TestLoginCommand:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(registry_auth, "_keyring", lambda: None)
        monkeypatch.setattr(registry_auth, "_AUTH_FILE", tmp_path / "auth.json")
        monkeypatch.delenv(registry_auth.ENV_TOKEN, raising=False)

    def test_login_token_stdin_then_logout(self):
        from click.testing import CliRunner

        from promptgenie.cli import cli

        runner = CliRunner()
        res = runner.invoke(cli, ["registry", "login", "ghcr.io", "--token-stdin"], input="abc\n")
        assert res.exit_code == 0
        assert registry_auth.get_token("ghcr.io") == "abc"
        out = runner.invoke(cli, ["registry", "logout", "ghcr.io"])
        assert out.exit_code == 0
        assert registry_auth.get_token("ghcr.io") is None

    def test_login_without_token_exit_2(self):
        from click.testing import CliRunner

        from promptgenie.cli import cli

        res = CliRunner().invoke(cli, ["registry", "login", "ghcr.io"])
        assert res.exit_code == 2


def test_oci_manifest_media_type(tmp_path: Path):
    # The remote store rewrites the manifest mediaType to the OCI type on the wire.
    reg = FakeOCIRegistry()
    store = _remote(reg, "myorg/x")
    bundle = build_artifact(_project(tmp_path), name="myorg/x", tag="v1")
    digest = push_bundle(store, bundle, "myorg/x", "v1")
    raw = json.loads(store.manifest_digest_bytes(digest))
    assert raw["mediaType"] == "application/vnd.oci.image.manifest.v1+json"
    assert Manifest.from_dict(raw).layers  # parses back into our model
