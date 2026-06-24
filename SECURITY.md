# Security Policy

## Supported Versions

| Version  | Supported          |
|----------|--------------------|
| 1.7.x    | ✓ Active (current) |
| 1.6.x    | ✓ Security patches |
| ≤ 1.5.x  | ✗ End of life      |

Current release: **1.7.0**. Patch releases are the only supported channel — no LTS or legacy branch exists. Upgrade to the latest 1.7.x to receive the security fixes listed below.

> The run-engine and VS Code extension hardening described in this document was introduced across the 1.2.x security-audit releases (the `(v1.2.x+)` markers on the sections below indicate when each control was added) and is included in every 1.7.x release.

---

## Reporting a Vulnerability

If you discover a security vulnerability in PromptGenie, please **do not open a public GitHub issue**.

Report it privately by emailing the maintainer or opening a [GitHub Security Advisory](https://github.com/mylesagnew/promptgenie/security/advisories/new).

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

You will receive an acknowledgement within **48 hours** and a resolution timeline within **7 days**.

---

## Run Engine Security Model (v1.2.3+)

The `promptgenie run` command executes PromptSpec YAML files that can name context sources,
provider URLs, and shell commands. The following hardened defaults are in effect from v1.2.3:

### Spec trust boundary

A PromptSpec can name context sources (`cmd`, `file`, `glob`, `env`, `url`) that read from — or
execute against — the host. Because a spec may arrive from an untrusted source (a cloned
repository, a shared gist), `promptgenie run` treats any spec containing a host-touching context
source as **untrusted until explicitly trusted**:

- On first run, an interactive session lists the dangerous context sources (the `cmd` strings,
  file paths, and URLs) and prompts for confirmation. On approval the spec is recorded as trusted.
- A non-interactive session (`--no-input`, CI) aborts with `exit 2` unless `--trust` or `--yes` is
  passed, or the spec was pre-registered with `promptgenie trust add`.
- Trust is keyed by the spec's **resolved absolute path and a hash of its content**. Editing a
  trusted spec invalidates the trust record and re-prompts — a trusted spec cannot be swapped for a
  malicious one without re-confirmation.
- The trust store lives at `~/.config/promptgenie/trust.json` (file mode `0600`, directory `0700`).
  Manage it with `promptgenie trust list | add <spec> | revoke <spec>`.
- Specs containing only an inline prompt and variables (no host-touching sources) do **not** require
  trust.

### Secrets gate — hard block

If the assembled prompt contains a HIGH or CRITICAL secret finding (API keys, tokens, credentials),
the run aborts with `exit 6` before any provider call is made. This prevents accidental credential
exfiltration to external LLM providers.

To bypass this gate in controlled environments (e.g. prompt injection test fixtures), pass
`--allow-secrets` to `promptgenie run`. A warning is printed to stderr whenever this flag is active.
Never use `--allow-secrets` in production pipelines that handle real credentials.

### URL context sources — SSRF protection

`context: [{type: url, url: ...}]` entries are validated before any network call:
- Only `https://` is permitted by default. `http://`, `file://`, `ftp://`, `data:`, and all other
  schemes raise `SecurityError`. Plain HTTP can be re-enabled with `--allow-insecure-url` (emits a
  security warning).
- **DNS rebinding defence with IP pinning** — the hostname is resolved via `socket.getaddrinfo()`
  before the connection is opened, and every returned IP is checked against the blocklist. From
  v1.2.3 the **validated IP is pinned for the actual connection** (the socket dials the checked IP
  while the original hostname is preserved in the `Host` header and TLS SNI/certificate
  verification). This closes the time-of-check/time-of-use window where a rebinding attacker could
  return a public IP to the validation lookup and a private IP to the connection.
- Requests to loopback addresses (`127.0.0.1`, `::1`), RFC-1918 private ranges (`10.x`,
  `172.16–31.x`, `192.168.x`), and link-local addresses (`169.254.x`) are blocked at both the
  URL-string level and the post-resolution level.
- **The egress gate is user-controlled only.** URL context sources are fetched only when the user
  passes `--allow-url`. From v1.2.4 a spec can no longer weaken this: the former spec-level
  `policy_gated` field has been removed, so an untrusted spec cannot enable network egress on its
  own behalf. (CWE-918 / secure-by-default.)

### Environment context sources — credential protection

`context: [{type: env, var: ...}]` entries refuse to read credential-like variables into the
prompt. Variable names matching common secret patterns (`*KEY*`, `*SECRET*`, `*TOKEN*`,
`*PASSWORD*`, `*CREDENTIAL*`, `*PRIVATE*`, `*SESSION*`, and `AWS_`/`AZURE_`/`GCP_`/`GOOGLE_`/
`OPENAI_`/`ANTHROPIC_`/`GITHUB_`/`SLACK_` prefixes) raise `SecurityError`. This prevents a spec
from pulling an API key or cloud credential into a prompt and exfiltrating it to a provider. The
`--allow-sensitive-env` flag overrides this with a printed warning.

### File context sources — path containment

`context: [{type: file, path: ...}]` entries are resolved to their real path (symlinks expanded)
and must fall within the project directory (the directory containing the spec file). Paths that
escape via `../`, absolute references, or symlink chains raise `SecurityError`.

### Command context sources — allowlist

`context: [{type: cmd, cmd: ...}]` entries are parsed with `shlex.split()` (no shell expansion)
and validated in three layers before any process is spawned (all `subprocess.run` calls use
`shell=False`):

1. **Executable allowlist** — the basename must be one of a small set of inert, read-only
   inspection tools (`git`, `cat`, `ls`, `grep`, `echo`, `pwd`, `date`, `uname`, `wc`, `head`,
   `tail`, `sort`, `uniq`, `cut`, `tr`, `printenv`). Interpreters and build tools (`python`,
   `python3`, `node`, `npm`, `make`, `env`, `awk`, `sed`, `find`, etc.) are **deliberately
   excluded** — each can execute arbitrary code despite a benign basename.
2. **Dangerous-argument denylist** — even for an allowlisted tool, any argument that is an
   eval/exec flag (`-c`, `-e`, `--eval`, `--eval=…`, `-exec`, `-execdir`, `--exec`) is rejected.
   This is defense-in-depth against future allowlist additions.
3. **`git` subcommand allowlist** — when the tool is `git`, the subcommand must be read-only
   (`log`, `diff`, `show`, `status`, `branch`, `rev-parse`, `ls-files`, `blame`, `describe`,
   `tag`, `remote`, `shortlog`). Mutating subcommands (`push`, `config <key> <value>`, …) and the
   `git -c …` config-injection form (which can alias a subcommand to a shell) are rejected.

Executables not on the allowlist (`rm`, `bash`, `sh`, `curl`, `nc`, and any other tool) raise
`SecurityError`.

### Provider endpoint validation

Provider `base_url` values (from `~/.config/promptgenie/providers.yaml`) are validated before any
request (`_validate_provider_base_url`, v1.2.4+):

- Non-HTTP(S) schemes are rejected.
- Plain `http://` is permitted **only** for loopback hosts (`localhost`, `127.0.0.1`, `::1`) or for
  providers explicitly marked `local: true` with no API key configured. This supports local dev
  servers (Ollama, LM Studio, vLLM) while preventing an `Authorization` header from ever being sent
  over cleartext to a remote endpoint (CWE-319).
- Remote providers must use `https://`.

---

## VS Code Extension Security Model (v1.2.2+)

> From **v1.2.4** the custom-binary trust check **fails closed**: if the extension context is
> unavailable (e.g. an activation-ordering bug), the extension refuses to execute the configured
> binary rather than allowing it by default.

### Trusted binary path enforcement

The extension resolves the CLI binary to execute via the `promptgenie.executablePath` setting
(falls back to `promptgenie` on `$PATH`). From v1.2.2, custom paths are validated before use:

- **Absolute path required** — relative paths are rejected unconditionally.
- **Basename check** — the resolved basename must be `promptgenie` or `promptgenie.exe`.
- **Regular file check** — the path must exist as a regular file (not a dangling symlink or
  directory).
- **Trust prompt for non-standard locations** — if a custom path is not under a recognised install
  prefix (`/usr/local/bin`, `~/.local/bin`, npm global bin, pipx bin), a one-time VS Code modal
  warning is shown: "This workspace has configured a custom PromptGenie binary at \<path\>. Do
  you trust this path?" The user's answer is stored in extension `globalState` (not workspace
  state) keyed by a hash of the absolute path, so it persists across sessions and cannot be reset
  by a workspace `.vscode/settings.json`.

### Setting scope: machine

`promptgenie.executablePath` (and the deprecated `promptgenie.cliPath`) use `scope: "machine"` in
`package.json`. This means workspace-level or folder-level `.vscode/settings.json` files **cannot
override** the binary path. Only user-level or machine-level settings apply. This prevents a
malicious repository from silently redirecting the extension to an arbitrary binary on clone.

> **If you manage VS Code settings via policy or MDM:** the `promptgenie.executablePath` setting
> can be locked at machine scope to a known-good path, preventing any per-user override.

---

## Scanner Limitations

The `promptgenie scan` command is a **heuristic scanner** — it is not a replacement for dedicated secret scanning or SAST tooling.

**What it is:**
- A fast, local, regex-based first-pass check for common risks in prompt files
- Accepts individual files, directories (recursive), and zip archives in a single run
- CI-safe: exits non-zero on HIGH or CRITICAL findings

**What it is not:**
- A comprehensive secret scanner (use `gitleaks` or `detect-secrets` for that)
- A static analysis tool
- Guaranteed to catch all prompt injection attempts
- A substitute for human review of high-risk agentic prompts

**Severity label semantics:**
`HIGH` and `CRITICAL` labels reflect the *severity of the pattern class*, not the certainty of detection. A `CRITICAL` finding means the matched pattern, if intentional, represents a critical risk — it does not mean the detection is certain or confirmed. Treat every finding as a heuristic signal and review before acting on it.

**Known limitations:**
- Secret detection covers common patterns (OpenAI, Anthropic, AWS, GitHub, Slack) but not all token formats
- No entropy-based detection — low-entropy or custom secret formats may be missed
- Allowlist and rule suppression are available via `.promptgenie.yaml` (`scanner.allowlist`, `scanner.disabled_rules`); see README for format
- Injection detection is pattern-based with NFKC Unicode normalisation; will miss synonym substitution, indirect reference, within-word character splits, non-NFKC homoglyphs (e.g. Turkish dotless ı), and multi-turn attacks
- See `tests/test_scanner_adversarial.py` for the full documented detection gap list

**Zip archive safety:**
Zip archives are extracted to a temporary directory before scanning. Every member path is validated against the extraction root before any extraction occurs (zip-slip protection). Archives containing absolute member paths, `..` traversal sequences, paths that resolve outside the extraction root, or Unix symlinks are rejected entirely — the archive is skipped and recorded as an error. The member count per archive is hard-capped at 1 000.

**Multi-file resource limits:**
Files collected across all paths are subject to a per-file byte cap (default 1 MB), a total-collection byte cap (default 10 MB), and a total-file count cap (default 500). Files exceeding these limits are skipped and reported via `--show-skipped`. Limits are configurable via `--max-files`, `--max-bytes`, and `--max-file-bytes`.

**Custom rules:**
Project-specific scanner rules can be added under `scanner.custom_rules` in `.promptgenie.yaml` (see README Configuration section). Each rule is a `ScanRule` with `id`, `category`, `pattern`, `risk`, `confidence`, `message`, `recommendation`, and optional `false_positive_note`. Custom rules are appended after built-in rules and participate in the same allowlist and severity-override system.

**Pattern safety:** custom rule patterns are validated at load time by `validate_pattern()` in `promptgenie/core/scanner.py`. Two checks are applied:

1. **Syntax** — `re.compile(pattern)` rejects patterns that are not valid Python regex.
2. **Nested quantifier detection** — patterns containing a quantified group that is itself quantified (e.g. `(a+)+`, `(\w+)*`, `(\d+){2,}`) are rejected. These constructs are the primary cause of catastrophic backtracking (ReDoS) and can cause the scanner to hang indefinitely on adversarial input. Rewrite such patterns using non-capturing groups or simplified alternatives.

Registry-installed rule packs are subject to the same validation at load time. A malformed pack raises `ValueError` and is never silently loaded.

---

## LLM Analysis External Transmission

The `promptgenie scan --llm` flag enables an **opt-in** LLM semantic analysis pass using an OpenAI-compatible API. This involves external transmission of prompt file content.

**Default state: OFF.** Without `--llm`, no LLM-related network call is ever made. The flag must be explicitly passed to enable analysis.

**Before sending, the command:**
1. Scans the content with the built-in heuristic secret-detection patterns and redacts any matches with `[REDACTED]` — the redacted text, not the original, is sent to the API
2. Truncates content to 8 000 characters per file
3. Requires `OPENAI_API_KEY` (or a custom env var) to be set — fails cleanly without it

**Privacy / air-gap mode:**
Pass `--no-external-llm` to suppress all LLM network calls even when `--llm` is also present. Use this in CI pipelines that run in environments where outbound API calls are prohibited, or when scanning prompt files that contain sensitive but non-secret content (internal architecture, PII, proprietary instructions).

**Redaction coverage:**
The pre-send redactor covers: OpenAI `sk-` keys, Anthropic `sk-ant-` keys, Google API keys (`AIza…`), AWS access key IDs (`AKIA…`), AWS secret access keys, GitHub PATs (`ghp_`/`ghs_`), Slack tokens (`xox…`), generic `api_key`/`token`/`secret`/`password` assignments ≥16 chars, and PEM private key headers. Redaction is conservative — it does not guarantee removal of all sensitive content. Review prompt files manually before enabling `--llm`.

**Do not use `--llm` with prompt files that contain:**
- Real API keys, tokens, or credentials (redaction is best-effort, not guaranteed)
- Personally identifiable information
- Internal system architecture details you do not want sent to a third party
- Proprietary business logic or IP

Use `--no-external-llm` in any CI pipeline where outbound LLM calls are not approved.

---

## Benchmark External Transmission

The `promptgenie benchmark` command sends prompt file content to Anthropic's API — once to the benchmark model, and once to the judge model. This is external transmission of your prompt data.

**Before sending, the command:**
1. Scans the prompt file with the built-in scanner and reports any secret findings with line numbers
2. Prints an explicit notice: which file, which API endpoint, how many calls
3. Requires interactive confirmation (`y/N`, defaulting to `N`) unless `--yes` / `-y` is passed

**Do not benchmark prompt files that contain:**
- Real API keys, tokens, or credentials
- Personally identifiable information
- Internal system architecture details you do not want sent to a third party

Use `--yes` only in CI pipelines where the prompt content has already been reviewed and cleared for external transmission.

---

## Safe Handling of Prompts Containing Secrets

- **Never embed real credentials in prompt files.** Use environment variable references instead: `$OPENAI_API_KEY`, `{{secret:my-key}}`.
- If a prompt file must reference a token for testing, use clearly fake placeholder values.
- Add `.promptignore` entries for files that legitimately discuss secrets in documentation context.
- The scanner reports the **class** of secret found, not the secret value itself — it will never print a matched credential to stdout.

---

## Dependency Security

- Dependencies are declared with lower-bound version pins in `pyproject.toml`.
- Run `pip-audit` to check for known vulnerabilities in the installed dependency tree:
  ```bash
  pip install pip-audit
  pip-audit
  ```
- Dependabot is configured for weekly `uv`, `github-actions`, and `npm` (vscode-extension) dependency update PRs.

---

## Supply Chain — Build Provenance, SBOM, and Verification

Every tagged release is built by the [`release.yml`](.github/workflows/release.yml) workflow on a tag matching `v[0-9]+.[0-9]+.[0-9]+`, gated behind a protected `release` environment. The pipeline:

- **Builds** the sdist + wheel with `uv build` and validates them with `twine check`.
- **Generates a CycloneDX SBOM** (`sbom.cyclonedx.json`) of the build environment.
- **Publishes to PyPI** via OIDC **Trusted Publishing** (no long-lived API token) with PEP 740 **attestations** enabled.
- **Attests build provenance** for the wheel and sdist (`actions/attest-build-provenance`) — a signed, GitHub-hosted SLSA provenance statement binding each artifact to the workflow, commit, and runner.
- **Attests the SBOM** (`actions/attest-sbom`) — a signed statement linking the SBOM to those same artifacts.
- **Creates a GitHub Release** with the wheel, sdist, and SBOM attached, and the changelog entry as release notes.

### Verifying a downloaded artifact

Use the GitHub CLI to verify both the provenance and the SBOM attestation against this repository before installing a downloaded wheel/sdist:

```bash
# Build provenance — confirms the artifact was built by this repo's release workflow
gh attestation verify ./promptgenie-1.7.0-py3-none-any.whl --repo mylesagnew/promptgenie

# SBOM attestation — confirms the published SBOM corresponds to this artifact
gh attestation verify ./promptgenie-1.7.0-py3-none-any.whl \
  --repo mylesagnew/promptgenie --predicate-type https://cyclonedx.org/bom
```

PyPI installs additionally carry PEP 740 attestations, which `pip`/`uv` surface as the ecosystem adds verification support. All workflow `uses:` actions are pinned by commit SHA.

---

## Rule and Profile Update Policy

- Scanner and linter rules are updated as new prompt injection techniques and secret formats become known.
- Profile YAML files (`promptgenie/profiles/*.yaml`) are community-editable — review any third-party profile before use.
- Rule updates follow semantic versioning: breaking changes to rule IDs or severities will be noted in the changelog.

---

## Out of Scope

The following are considered out of scope for vulnerability reports:
- False positives or false negatives in heuristic scanning (file a regular issue instead)
- Security of the model or API you send generated prompts to
- Prompt injection attacks against the model receiving the prompt (the tool helps you write safer prompts, it does not sandbox the model)
