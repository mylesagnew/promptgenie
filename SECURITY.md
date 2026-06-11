# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.2.x   | ✓ Active (current) |
| 1.1.x   | ✓ Security patches |
| 1.0.x   | ✗ End of life      |
| < 1.0   | ✗ End of life      |

Current release: **1.2.1**. Patch releases are the only supported channel — no LTS or legacy branch exists. Users on 1.0.x should upgrade to 1.2.x to receive the security fixes listed below.

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

## Run Engine Security Model (v1.2.1+)

The `promptgenie run` command executes PromptSpec YAML files that can name context sources,
provider URLs, and shell commands. The following hardened defaults are in effect from v1.2.1:

### Secrets gate — hard block

If the assembled prompt contains a HIGH or CRITICAL secret finding (API keys, tokens, credentials),
the run aborts with `exit 6` before any provider call is made. This prevents accidental credential
exfiltration to external LLM providers.

To bypass this gate in controlled environments (e.g. prompt injection test fixtures), pass
`--allow-secrets` to `promptgenie run`. A warning is printed to stderr whenever this flag is active.
Never use `--allow-secrets` in production pipelines that handle real credentials.

### URL context sources — SSRF protection

`context: [{type: url, url: ...}]` entries are validated before any network call:
- Only `http://` and `https://` schemes are permitted. `file://`, `ftp://`, `data:`, and all other
  schemes raise `SecurityError`.
- Requests to loopback addresses (`127.0.0.1`, `::1`), RFC-1918 private ranges (`10.x`,
  `172.16–31.x`, `192.168.x`), and link-local addresses (`169.254.x`) are blocked.
- URL context sources are additionally gated behind the `--allow-url` CLI flag.

### File context sources — path containment

`context: [{type: file, path: ...}]` entries are resolved to their real path (symlinks expanded)
and must fall within the project directory (the directory containing the spec file). Paths that
escape via `../`, absolute references, or symlink chains raise `SecurityError`.

### Command context sources — allowlist

`context: [{type: cmd, cmd: ...}]` entries are parsed with `shlex.split()` (no shell expansion)
and the executable basename is checked against a fixed allowlist of safe tools (`git`, `cat`,
`grep`, `python3`, `make`, and a small set of equivalents). Executables not on the allowlist
(`rm`, `bash`, `sh`, `curl`, `nc`, and any other tool) raise `SecurityError` before any process
is spawned.

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
