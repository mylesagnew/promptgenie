# PromptGenie Threat Model

This document describes the assets PromptGenie handles, the trust boundaries it
sits across, the attackers it defends against, and how each threat maps to a
concrete control in the codebase. It complements [SECURITY.md](SECURITY.md)
(which documents the controls in prose) by making the *threat → control*
mapping explicit and reviewable.

Scope: the `promptgenie` CLI/library and the bundled VS Code extension. Out of
scope: the safety of the LLM provider you send prompts to, and prompt-injection
attacks against that model (PromptGenie helps you *author* safer prompts; it
does not sandbox the receiving model).

---

## 1. Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| **Prompt / context content** | `.md`/`.prompt.yaml` files, assembled context | May embed proprietary logic, internal architecture, or PII |
| **Secrets & credentials** | provider API keys, env vars, `providers.yaml`, keyring | Disclosure = account compromise / spend |
| **Run history** | `~/.local/share/promptgenie/` (NDJSON + SQLite) | Can accumulate prompts/responses over time |
| **Trust store** | `~/.config/promptgenie/trust.json` | Decides which specs may run host-touching sources |
| **Provider config** | `~/.config/promptgenie/providers.yaml` | Controls where prompts (and auth headers) are sent |
| **The developer host** | shell, filesystem, network | A spec can name `cmd`/`file`/`url` sources that touch it |

---

## 2. Trust boundaries

```
        untrusted inputs                    PromptGenie process                external
 ┌──────────────────────────┐      ┌──────────────────────────────┐     ┌──────────────────┐
 │ cloned repo / shared spec │ ───► │  spec trust gate             │     │ LLM provider API │
 │ retrieved RAG/url content │ ───► │  context builder (gates)     │ ──► │ (egress)         │
 │ prompt files under review │ ───► │  scanner / secrets gate      │     │ secret manager   │
 │ workspace .vscode settings│ ───► │  VS Code extension (binary)  │     │ PyPI (install)   │
 └──────────────────────────┘      └──────────────────────────────┘     └──────────────────┘
```

The critical boundary is **"a spec/prompt may arrive from an untrusted source"**
(a cloned repository, a shared gist, a teammate's PR). Such a spec can name
context sources that read files, run commands, or fetch URLs on the host, and
can contain content destined for an external provider.

---

## 3. Attacker model

- **A1 — Malicious repository / spec author.** Ships a `.prompt.yaml` whose
  context sources execute code, exfiltrate files/secrets, or reach internal
  network services when a victim runs it.
- **A2 — Malicious retrieved content.** A `url`/RAG source returns content
  crafted to trigger SSRF or to smuggle instructions.
- **A3 — Local data thief / other local user.** Tries to read prompts,
  responses, or credentials from history/config files on a shared machine.
- **A4 — Supply-chain attacker.** Tampers with a released artifact or a CI
  dependency/action.
- **A5 — Malicious workspace config.** A cloned repo's `.vscode/settings.json`
  tries to redirect the extension to an arbitrary binary.

---

## 4. Threats → controls

| ID | Threat (attacker) | Control | Where |
|---|---|---|---|
| T1 | Untrusted spec runs `cmd`/`file`/`url` sources on first invocation (A1) | **Spec trust gate** — host-touching specs are untrusted until confirmed; trust keyed by path + content hash; non-interactive aborts without `--trust`/`--yes` | `core/trust.py`, `commands/run.py` (`_trust_gate`) |
| T2 | Arbitrary command execution via a `cmd` source (A1) | **Executable allowlist** (inert read-only tools only), **eval-flag denylist**, **`git` read-only subcommand allowlist**, `shell=False` | `core/context_builder.py` |
| T3 | SSRF / internal-network access via a `url` source (A1, A2) | **`https`-only by default**, **DNS-rebinding defence with IP pinning**, loopback/RFC-1918/link-local blocked; egress requires user `--allow-url` (spec cannot self-enable) | `core/context_builder.py` |
| T4 | Credential exfiltration via an `env` source (A1) | **Credential-like env var names refused** (`*KEY*`/`*SECRET*`/`*TOKEN*`/… and cloud prefixes) unless `--allow-sensitive-env` | `core/context_builder.py`, `commands/run.py` |
| T5 | Path traversal via a `file`/`glob` source (A1) | **Project-directory containment** — real path must stay within the spec dir; `..`/symlink escapes rejected | `core/context_builder.py` |
| T6 | Secrets sent to an external provider in the prompt (A1, user error) | **Pre-send secrets gate** — HIGH/CRITICAL findings hard-block before any provider call unless `--allow-secrets`; optional `--redact-secrets` | `core/run_engine.py` (`_check_secrets_gate`/`_apply_secrets_gate`) |
| T7 | Auth header sent over cleartext to a remote endpoint (A2) | **Provider `base_url` validation** — non-HTTP(S) rejected; plain `http://` only for loopback / keyless-local providers | `core/providers.py` (`_validate_provider_base_url`) |
| T8 | External provider call in an air-gapped environment (policy) | **Air-gap mode** blocks all non-local providers | `core/providers.py` (`get_provider`), `security.airgap` |
| T9 | Local theft of prompts/responses from run history (A3) | **Metadata-only history by default** (bodies + tokens not persisted; opt-in is redacted); files `0600`, dirs `0700` | `core/history.py`, `core/history_db.py`, `security.store_history_content` |
| T10 | Theft of credentials at rest (A3) | **Keyring-backed credential storage**; external-secret `ref:` resolution at runtime; never logged | `core/credentials.py` |
| T11 | Trust store tampered or weakened (A3) | Trust file `0600` / dir `0700`; trust invalidated on spec content change | `core/trust.py` |
| T12 | Malicious workspace redirects the extension binary (A5) | **Binary path validation** (absolute, basename, regular-file), **trust prompt** for non-standard paths persisted in global state, **`scope: machine`** setting so workspace config can't override; **fails closed** when context is unavailable | `vscode-extension/src/runner.ts` |
| T13 | Extension DoS via huge/hung CLI output (A1 via a crafted prompt) | **Bounded subprocess output** (8 MB/stream cap, kill on overflow) + **30 s watchdog timeout** | `vscode-extension/src/runner.ts` |
| T14 | ReDoS via a hostile custom/registry scanner rule (A1) | **Pattern validation** at load — syntax check + nested-quantifier rejection | `core/scanner.py` (`validate_pattern`) |
| T15 | Zip-slip via a scanned archive (A1) | **Per-member path validation** before extraction; symlinks/absolute/`..` rejected; member cap | `core/scanner.py` |
| T16 | Tampered release artifact (A4) | **OIDC Trusted Publishing**, **build-provenance attestation**, **SBOM attestation**, SHA-pinned actions, protected `release` environment | `.github/workflows/release.yml` |
| T17 | Leaked secret committed to the repo (A4, user error) | **gitleaks** secret scan fails CI; **version-drift gate** keeps security docs honest | `.github/workflows/ci.yml` |
| T18 | Prompt content sent to a third party by an opt-in analysis path (user error) | `scan --llm` is **off by default**, pre-redacts before send, supports `--no-external-llm`; `benchmark` requires explicit confirmation | `core/llm_analyzer.py`, `commands/benchmark.py` |

---

## 5. Residual risk & assumptions

- The heuristic **scanner is a tripwire, not a guarantee** — it misses synonym
  substitution, indirect reference, non-NFKC homoglyphs, and multi-turn attacks
  (see `tests/test_scanner_adversarial.py`). Treat findings as signals.
- Controls assume a **single-user, owner-trusted home directory**; file-mode
  hardening does not defend against root or a compromised OS account.
- PromptGenie does **not** sandbox the LLM that receives a prompt; it reduces
  the chance of sending something dangerous, not the model's behaviour.
- The **opt-in** escape hatches (`--allow-url`, `--allow-sensitive-env`,
  `--allow-secrets`, `security.store_history_content`) intentionally trade
  safety for capability; they are off by default and emit warnings.

---

## 6. Reporting

Security issues: see [SECURITY.md](SECURITY.md#reporting-a-vulnerability). Please
do not open a public issue for a vulnerability.
