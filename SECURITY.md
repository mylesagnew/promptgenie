# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | ✓ Active  |

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

## Scanner Limitations

The `promptgenie scan` command is a **heuristic scanner** — it is not a replacement for dedicated secret scanning or SAST tooling.

**What it is:**
- A fast, local, regex-based first-pass check for common risks in prompt files
- Useful for catching obvious issues before sending a prompt to a model
- CI-safe: exits non-zero on HIGH or CRITICAL findings

**What it is not:**
- A comprehensive secret scanner (use `gitleaks` or `detect-secrets` for that)
- A static analysis tool
- Guaranteed to catch all prompt injection attempts
- A substitute for human review of high-risk agentic prompts

**Known limitations:**
- Secret detection covers common patterns (OpenAI, Anthropic, AWS, GitHub, Slack) but not all token formats
- No entropy-based detection — low-entropy or custom secret formats may be missed
- No allowlist or suppression mechanism yet (planned in P1 roadmap)
- Injection detection is pattern-based and may miss novel jailbreak techniques
- Results should be treated as advisory, not authoritative

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
- Dependabot / Renovate integration is on the roadmap for automated dependency updates.

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
