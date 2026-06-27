# Design Scope — Prompt Registry (Phase 6)

> Status: **Phase A implemented** (local-first) · Phase B (remote) deferred
> Roadmap: Phase 6 — Governance, SSO, and Cloud Sync
> Code: `core/registry_store.py`, `core/artifact.py`, `core/registry_signing.py`,
> `commands/registry_cmd.py`, `schemas/prompt-manifest.schema.json` ·
> Tests: `tests/test_prompt_registry.py` (41)

## Implementation notes (deviations from the original scope)

- **Store location** is resolved from `--store-path` → `PROMPTGENIE_REGISTRY_PATH`
  → the user-global default, rather than a `registry.store_path` config key. This
  keeps the config schema/validation surface untouched this milestone; the flag
  and env var already cover the in-project (`.promptgenie/registry`) case. A
  config key can be added later without changing behaviour.
- **Air-gap** is a no-op for Phase A because the local store makes no network
  calls — it is inherently air-gap-safe. The `security.airgap` gate is wired in
  Phase B, where the remote backend is the only thing to block.
- **Reproducibility:** layer blobs are byte-reproducible and dedupe across
  pushes; the *manifest* digest includes a `created` timestamp (like an OCI
  image), so re-pushing identical content yields a new manifest digest while the
  underlying layers are shared. A `--reproducible` flag (zeroed timestamp) is a
  possible future addition.

## 1. Goal

A versioned, signed, searchable store for prompt artifacts with an
OCI-inspired, content-addressable layout:

```bash
promptgenie registry push prompts/auth-review.promptgenie.yaml --tag v1.2
promptgenie registry pull org/auth-review:latest --out ./vendored
```

The registry makes a prompt (and everything it needs to run) a
**reproducible, addressable, verifiable artifact** — the same way a container
image bundles an app. It is the storage substrate the rest of Phase 6 (remote
eval runners, team policy, VSCode Phase 2) builds on.

Two delivery phases:

- **Phase A — local-first (this milestone).** A filesystem-backed store with the
  full push/pull/list/show/verify/search/gc surface, signing, digest
  verification, audit provenance, and air-gap enforcement. Fully testable
  offline; no server, no new runtime dependencies.
- **Phase B — remote (follow-up).** An HTTPS backend speaking the same
  manifest/blob protocol; `registry login`, push/pull over the wire; ties into
  the SSO/OIDC item.

## 2. What is a "prompt artifact"?

Everything needed to reproduce a prompt run — exactly the input set the lockfile
already enumerates (`core/lockfile.py`):

| Layer | Source |
|---|---|
| PromptSpec (or Markdown prompt) | the pushed file |
| Template(s) | `spec.template` resolution |
| Policy file(s) | `spec.policy` |
| Context pack / context source manifest | `spec.context` |
| Output schema(s) | `output_contract.schema` (file refs) |
| Variable files | `--vars` style references |

Plus a **config blob** of prompt-level metadata (name, description,
provider/model pin, classification) and an optional **signature** over the
manifest.

## 3. OCI-inspired layout (filesystem)

Mirror the OCI distribution model — content-addressed blobs + manifest + tag
index — on disk:

```
<store-root>/
  blobs/sha256/<digest>        # every input file, stored once, content-addressed
  manifests/sha256/<digest>    # artifact manifest (JSON), itself content-addressed
  index.json                   # repo:tag -> manifest digest  (OCI image-index-like)
```

Default `<store-root>`: `~/.local/share/promptgenie/registry` (user-global),
overridable by `registry.store_path` config or `--store-path`. An in-project
mode (`.promptgenie/registry`, committable for vendoring) is selectable.

### Manifest schema (`schemas/prompt-manifest.schema.json`)

```json
{
  "schemaVersion": 2,
  "mediaType": "application/vnd.promptgenie.prompt.manifest.v1+json",
  "config": { "mediaType": "application/vnd.promptgenie.prompt.config.v1+json", "digest": "sha256:…", "size": 412 },
  "layers": [
    { "mediaType": "application/vnd.promptgenie.spec.v1+yaml",     "digest": "sha256:…", "size": 1024,
      "annotations": { "org.promptgenie.path": "auth-review.promptgenie.yaml" } },
    { "mediaType": "application/vnd.promptgenie.template.v1+markdown", "digest": "sha256:…", "size": 800,
      "annotations": { "org.promptgenie.path": "templates/review.md" } },
    { "mediaType": "application/vnd.promptgenie.policy.v1+yaml",   "digest": "sha256:…", "size": 256,
      "annotations": { "org.promptgenie.path": "promptgenie.policy.yaml" } }
  ],
  "annotations": {
    "org.promptgenie.name": "auth-review",
    "org.promptgenie.tag": "v1.2",
    "org.opencontainers.image.created": "2026-06-27T10:00:00Z"
  }
}
```

The signature covers the **manifest digest**, which transitively covers every
layer (each referenced by digest) — sign once, verify the whole bundle.

## 4. Reference grammar

```
[host/]namespace/name[:tag][@sha256:<digest>]
```

Examples: `org/auth-review:v1.2`, `org/auth-review@sha256:abcd…`,
`auth-review:latest` (local). Default tag `latest`. A digest pin (`@sha256:`)
wins over a tag and makes a pull fully immutable.

## 5. CLI surface — `promptgenie registry`

| Command | Behaviour |
|---|---|
| `push <spec\|prompt> --tag T [--name REPO] [--sign --key K --method minisign\|cosign] [--annotate k=v]…` | Walk dependencies (reuse lockfile), content-address each layer into `blobs/`, write config + manifest, point `index.json[REPO:T]` at the manifest digest; optionally sign the manifest blob. |
| `pull <ref> [--out DIR] [--require-signed] [--pubkey K] [--method]` | Resolve ref → manifest, verify every layer digest (fail-closed), verify signature if requested, materialise files into DIR by their `org.promptgenie.path` annotations (path-traversal-guarded). |
| `list [--name REPO] [--format json]` | List repos/tags in the store. |
| `tags <REPO>` | List tags for a repo, newest first. |
| `show <ref> [--format json]` | Print manifest, layers, sizes, digests, provenance. |
| `verify <ref> --pubkey K [--method]` | Verify signature + recompute/verify all digests. |
| `rm <ref>` | Remove a tag from the index (blobs left for `prune`). |
| `prune [--dry-run]` | GC blobs/manifests no longer referenced by any tag. |
| `search <query> [--format json]` | Match name / annotations / classification across the store (and remote index when configured — Phase B). |

Global: `--store-path PATH` / `--store local` (default). Phase B adds
`--store <url>` + `registry login`.

## 6. Reuse map (what we do *not* rebuild)

| Need | Existing code |
|---|---|
| Enumerate artifact layers | `core/lockfile.py` dependency walk (`create_lockfile`) |
| Content hashing | `lockfile._sha256_file` / `_sha256_str` (`sha256:<hex>`) |
| Signature **verify** | `core/pack_signing.verify_pack_signature(path, pubkey, method)` |
| Signature **sign** (new helper) | shell out to `minisign -S` / `cosign sign-blob`, mirroring the verify shape |
| Remote download safety (Phase B) | `core/registry.py`: `_validate_url` (HTTPS-only), `_download_to_temp`, `_verify_sha256`, size caps |
| Provenance | `core/audit.write_audit_event(...)` — tamper-evident hash chain |
| Air-gap enforcement | `config.SecurityConfig.airgap` (same gate `providers.get_provider` uses) |
| Bounded/atomic IO | `core/fileio.safe_read_text` / `safe_write_text` |
| Command structure / structured output | `commands/pack.py` group, `is_structured_mode`, `schema_version: "1.0"` |

## 7. Security posture

- **Content-addressed, fail-closed.** Every layer and the manifest are verified
  by digest on pull; any mismatch aborts (`EXIT_FAILURE`).
- **Optional signing, enforceable.** `--require-signed` refuses unsigned (or
  bad-signature) artifacts on pull. Signature covers the manifest digest.
- **Air-gap aware.** Local store always works; remote push/pull is blocked when
  `security.airgap` is set (Phase B), mirroring the provider gate.
- **Path-traversal guard.** `org.promptgenie.path` annotations are sanitised on
  materialise — reject absolute paths and `..`; everything lands under `--out`.
- **Audited.** Each push/pull writes an audit event (action, ref, digest, time)
  to the existing hash-chained log.
- **HTTPS-only + size caps** for the remote backend (Phase B), reusing the
  `registry.py` patterns.

## 8. New modules & tests

```
promptgenie/core/artifact.py          # build_artifact(spec) -> (Manifest, {digest: bytes}); materialise()
promptgenie/core/registry_store.py    # Reference parser; Manifest/Descriptor; LocalRegistryStore
promptgenie/commands/registry_cmd.py  # the `registry` command group
promptgenie/schemas/prompt-manifest.schema.json
tests/test_registry_store.py          # round-trip, tamper detection, ref parsing, GC, air-gap, traversal guard, signing (mocked)
```

Config additions: `registry.store_path`, `registry.default_remote` (Phase B).

**Estimated size:** ~600–900 LoC core + ~300 command + ~40 tests, one focused
milestone. No new runtime dependencies (minisign/cosign remain optional external
CLIs, already used by `pack verify`).

## 9. Decisions (confirmed)

1. **Milestone scope** — ✅ **Phase A (local-first) only.** Ship the filesystem
   store end-to-end; scope the Phase B remote backend as a separate milestone.
2. **Default store location** — ✅ **User-global** (`~/.local/share/promptgenie/registry`),
   like the audit/history DBs. In-project mode (`.promptgenie/registry`,
   committable for vendoring) available via `--store-path` / `registry.store_path`.
3. **OCI fidelity** — ✅ **OCI-inspired.** Our own `application/vnd.promptgenie.*`
   media types and an image-index-like layout, kept close enough to adopt strict
   OCI in Phase B without a breaking change.

## 10. Phase A build order (when greenlit)

1. `core/registry_store.py` — `Reference` parser + `Descriptor`/`Manifest`
   dataclasses + `LocalRegistryStore` (blob/manifest put/get, `index.json`
   read/write, `resolve_ref`, `list_repos`, `gc`). Unit-test in isolation.
2. `core/artifact.py` — `build_artifact(spec)` (lockfile-driven layering) and
   `materialise(manifest, store, out_dir)` (path-traversal-guarded).
3. `schemas/prompt-manifest.schema.json` + a `sign_blob` helper in
   `core/pack_signing.py`.
4. `commands/registry_cmd.py` — the command group; wire into `cli.py`.
5. Config keys (`registry.store_path`) + audit events + air-gap gate.
6. `tests/test_registry_store.py` + docs (README, ROADMAP, CHANGELOG).
```

---

# Phase B — Remote Registry Backend (scope)

> Status: **B.1 implemented** (token auth + OCI remote) · **B.2 (SSO/OIDC) deferred**
> Code: `core/registry_remote.py`, `core/registry_backend.py`, `core/registry_auth.py`,
> remote wiring in `commands/registry_cmd.py` · Tests: `tests/test_registry_remote.py` (18)
>
> **B.1 implementation notes.** The remote store is *repository-bound*, so its
> method signatures match the local store and `push_bundle` / `materialise` /
> `registry_signing` work unchanged across both (no shared-Protocol surgery at the
> call sites; a `RegistryStore` Protocol types the boundary). Remotes resolve from
> `--remote` / a host embedded in the reference / `PROMPTGENIE_REGISTRY_TOKEN`;
> the deferred `registry.*` config section was **not** added this milestone (it
> would touch the workspace-schema validator), so named remotes via config remain
> a follow-up. Tests use httpx's in-process `MockTransport` (a fake OCI registry)
> — no `respx`, no live network. Registries requiring a `WWW-Authenticate` token
> *exchange* handshake (vs a static bearer) are a B.1 follow-up.

## B.1 Goal

```bash
promptgenie registry login ghcr.io --token-stdin < token.txt
promptgenie registry push org/auth-review:v1.2 --remote ghcr.io/myorg
promptgenie registry pull ghcr.io/myorg/auth-review:v1.2 --require-signed --pubkey pg.pub
```

Same artifact model, same digest-verified, signature-anchored trust — over the
wire instead of the filesystem.

## Architecture — backend abstraction

Introduce a `RegistryBackend` Protocol capturing exactly what the CLI needs, with
two implementations behind it:

- `LocalRegistryStore` (Phase A) — refactored to satisfy the protocol.
- `RemoteRegistryStore` (Phase B) — an HTTPS client.

Protocol surface (content-addressable, transport-agnostic):

```
has_blob(digest) -> bool          put_blob(data, media_type) -> Descriptor
get_blob(digest) -> bytes         put_manifest(manifest) -> digest
get_manifest(digest) -> Manifest  resolve_ref(ref) -> digest
set_tag(repo, tag, digest)        all_tags() / list_tags(repo)
find_signature(digest)            put_signature(digest, data, method)
```

The push/pull/list/show logic in `registry_cmd.py` becomes backend-agnostic;
`resolve_backend(--remote / config / --store-path)` picks the implementation.

## Wire protocol (OCI-distribution-inspired)

```
GET  /v2/                              version / capability probe
HEAD /v2/<repo>/blobs/<digest>         blob exists?  (drives push dedup)
GET  /v2/<repo>/blobs/<digest>         blob bytes
POST /v2/<repo>/blobs/uploads/ + PUT   upload blob (server re-checks digest)
GET  /v2/<repo>/manifests/<ref>        manifest by tag or digest
PUT  /v2/<repo>/manifests/<tag>        point tag at a manifest
GET  /v2/<repo>/tags/list              tags
GET  /v2/_catalog                      repositories (search)
GET  /v2/<repo>/signatures/<digest>    detached signature (PromptGenie extension)
PUT  /v2/<repo>/signatures/<digest>    upload signature
```

`Authorization: Bearer <token>`; `401` triggers login/refresh.

**Push** (dedup-aware): build artifact locally → `HEAD` each blob, `PUT` only the
missing ones (shared layers upload once) → `PUT` manifest by tag → `PUT`
signature if `--sign`. **Pull**: `GET` manifest by ref → verify digest → `GET`
each layer → verify digest → reuse Phase A `materialise`; `--require-signed`
fetches and verifies the signature first.

## Trust model — the server is untrusted

Every blob and manifest is **verified client-side against its digest**
(fail-closed). A digest pin (`@sha256:`) or a `--require-signed` + pinned pubkey
gives **end-to-end integrity independent of the transport or the registry
operator** — a compromised server cannot substitute content. This is the whole
point of keeping content-addressing and manifest signing from Phase A.

## Security

- **HTTPS-only** via the existing `_validate_url` SSRF guard; reject
  `http`/`file`/etc. **Size caps** on every download (reuse `_MAX_DOWNLOAD_BYTES`,
  make configurable).
- **TLS verification on by default**; `--insecure` is explicit and warns loudly
  (mirrors provider TLS handling). Reuse the existing DNS-rebinding / IP-pinning
  hardening for outbound fetches.
- **Air-gap now bites**: `security.airgap` blocks all remote backends (mirroring
  `providers.get_provider`); the local store still works.
- **Tokens** stored in the keyring (`credentials.store_credential("registry:<host>", …)`),
  never logged, redacted in audit; `PROMPTGENIE_REGISTRY_TOKEN` for CI.
- **Audit**: `login` / `push` / `pull` events carry remote host, ref, digest, user.

## Authentication — ties into the SSO/OIDC roadmap item

- **B.1 — token**: `registry login <remote> --token-stdin`, `registry logout`,
  keyring-backed, CI env var. Ships first; fully mockable in tests.
- **B.2 — SSO/OIDC**: `registry login --sso` → OIDC device flow → short-lived
  token, per-user audit attribution. This is exactly the roadmap's
  "SSO/OIDC credential binding" item; the registry is its first consumer, so the
  two are delivered together.

## New modules & tests

```
core/registry_backend.py   # RegistryBackend Protocol + resolve_backend()
core/registry_remote.py    # RemoteRegistryStore (HTTP client, dedup HEAD checks)
core/registry_auth.py      # token store/login/logout; (B.2) OIDC device flow
config.py                  # RegistryConfig: default_remote, remotes, max_download_bytes, tls_verify
tests/test_registry_remote.py  # mock transport: round-trip, dedup, malicious-server digest mismatch,
                               # 401->login, airgap block, --insecure, token redaction
```

Optional extra: reuse the existing `httpx` (already in `providers`/`llm`) or stay
on stdlib `urllib` (zero new dep). OIDC device flow can be hand-rolled on
`urllib` to avoid a new dependency.

## Build order

1. `RegistryBackend` Protocol; make `LocalRegistryStore` conform; route the CLI
   through `resolve_backend`.
2. `RegistryConfig` in `config.py` (also retrofits Phase A's `--store-path` to a
   config key).
3. `RemoteRegistryStore` + `registry login/logout` (B.1 token) against a mock
   transport.
4. Wire `--remote` through push/pull/list/show/tags/search; air-gap gate; audit.
5. (B.2) OIDC device flow + per-user attribution.

## Decisions (confirmed)

1. **Wire target** — ✅ **OCI registries.** Target existing OCI registries
   (ghcr.io / Zot / Harbor) via strict OCI artifact media types; *no server to
   run*. Implies a compatibility step: emit strict-OCI manifest/media types on
   the remote path (the local store's `application/vnd.promptgenie.*` types map
   to OCI artifact layers; keep a translation shim so Phase A stores stay valid).
2. **HTTP client** — ✅ **Reuse `httpx`** (already in the `providers`/`llm`
   extras); the remote backend lives behind an extra so the base install stays
   dependency-free. Mock with `respx` in tests.
3. **Auth scope** — ✅ **B.1 token only** this milestone (keyring + CI env var +
   `login`/`logout`). **B.2 SSO/OIDC** is a separate follow-up that delivers the
   roadmap's SSO item, with the registry as its first consumer.

### OCI compatibility note

Targeting real OCI registries tightens the Phase A "OCI-inspired" decision *for
the wire only*: the remote backend pushes an OCI image manifest
(`application/vnd.oci.image.manifest.v1+json`) whose config + layers use OCI
artifact media types, with our PromptGenie kinds carried in layer
`annotations`. The local on-disk store is unaffected — `RemoteRegistryStore`
translates between our `Manifest` and the OCI manifest at the boundary. Detached
signatures map to an OCI referrers / cosign-style attachment (or the
`/signatures/` extension when the target lacks referrers support).
