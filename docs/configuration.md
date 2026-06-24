# PromptGenie — Configuration Reference

Full `.promptgenie.yaml` reference and config CLI. Back to the [README](../README.md).

## Configuration

Place a `.promptgenie.yaml` file in your project root (or any parent directory). All commands auto-discover and load it. Run `promptgenie config init` to scaffold one with the JSON Schema pointer and editor autocomplete pre-wired.

**Full schema:** `promptgenie/schemas/workspace.schema.json` (Draft 2020-12). All sections enforce `additionalProperties: false` — typos in key names are caught by `config validate`.

```yaml
# yaml-language-server: $schema=https://promptgenie.dev/schemas/workspace.schema.json
$schema: "https://promptgenie.dev/schemas/workspace.schema.json"

# Project-level metadata (optional — used in policy server and audit trail)
workspace:
  name: "my-project"
  version: "1.0"
  team: "platform-eng"
  description: "Prompt engineering workspace for the payments API."
  policy: ".promptgenie-policy.yaml"   # default policy file

# Workspace-wide defaults — overridden by --provider/--model/--target CLI flags
defaults:
  provider: anthropic
  model: claude-opus-4-5
  target: claude-code

scanner:
  # Allowlist entries suppress findings whose *matched text* contains the phrase.
  # Suppression is scoped to the finding's match — not the whole prompt.

  # Simple string: suppresses any finding whose matched text contains this phrase.
  allowlist:
    - "example-token-for-docs"

  # Scoped object: suppress only specific rule codes when the phrase is matched.
  # Safer — won't accidentally suppress unrelated findings on the same line.
  #   - phrase: "known-safe-deploy"
  #     rules:
  #       - PERM_005

  # Expiring suppression — automatically deactivates after the ISO date.
  # Use for time-limited exceptions (CI placeholders, short-lived tokens).
  #   - phrase: "sk-ant-ci-placeholder"
  #     rules:
  #       - SEC_SECRET
  #     expires: "2026-12-31"
  #     reason: "CI placeholder — rotate before expiry, see ticket #456"

  # Disable specific rule codes entirely (no phrase check needed)
  disabled_rules:
    - SEC_007

  # Whitelist mode — ONLY run these rule codes (takes precedence over disabled_rules)
  # Use SEC_SECRET to target all secret sub-rules at once (SEC_SECRET_AWS_KEY, SEC_SECRET_GITHUB, etc.)
  # enabled_rules:
  #   - SEC_SECRET
  #   - OWASP_LLM01_001

  # Override the default risk level for a rule
  severity_overrides:
    PERM_005: CRITICAL

  # Extra directories to load rule packs from (supports ~ expansion)
  # Each *.yaml file is scanned for a scanner_rules key
  # rules_dirs:
  #   - ~/.promptgenie/registry/packs
  #   - ./local-rules

linter:
  # Disable specific lint rules
  disabled_rules:
    - TASK_003

  # Whitelist mode — ONLY run these codes
  # enabled_rules:
  #   - TASK_001
  #   - ENT_001

  # Extra directories to load lint rule packs from
  # rules_dirs:
  #   - ~/.promptgenie/registry/packs

  # Add project-specific vague verbs beyond the built-in list
  custom_vague_verbs:
    - "tidy"
    - "polish"

  # Add custom lint rules (appended after built-in rules)
  custom_rules:
    - id: MY_LINT_001
      category: custom
      pattern: "refactor everything"
      severity: HIGH
      confidence: HIGH
      message: "Overly broad refactor instruction."
      suggestion: "Narrow the refactor to specific modules or files."
```

**Custom scanner rules** can also be added under `scanner.custom_rules`. Each rule requires `id`, `pattern`, `risk`, `confidence`, `message`, and `recommendation`. All patterns are validated at load time — syntax errors and nested quantifiers (ReDoS risk) raise `ValueError` and abort config loading:

```yaml
scanner:
  custom_rules:
    - id: MY_SEC_001
      category: custom
      pattern: "disable (all )?logging"
      risk: HIGH
      confidence: MEDIUM
      message: "Logging suppression detected — may hide audit trail."
      recommendation: "Retain audit logs. Use log-level configuration instead."
      false_positive_note: "May trigger on prompts about log configuration."
```

### Config CLI flags

The `scan`, `lint`, `generate`, `adapt`, and `workflow` commands all accept:

| Flag | Effect |
|---|---|
| `--config PATH` | Load a specific config file instead of auto-discovering `.promptgenie.yaml` |
| `--no-config` | Ignore any `.promptgenie.yaml`; run with default settings |
| `--best-effort` | Fall back to built-in defaults on missing profile, template, or config (fail-open) |

When a config file is loaded in rich output mode, its path is shown as a dim line before results. A missing or malformed `--config` file is a **fatal error** by default — pass `--best-effort` to fall back to defaults instead.

### Config management commands

```bash
# Scaffold a new .promptgenie.yaml with schema pointer
promptgenie config init
promptgenie config init --name "my-project" --force   # overwrite existing

# Validate .promptgenie.yaml against the workspace schema
promptgenie config validate                            # exits 0 = valid, 1 = errors, 2 = not found
promptgenie config validate --format json              # machine-readable for CI
promptgenie config validate --config path/to/file.yaml

# Show current effective config
promptgenie config show
promptgenie config show --format json

# Get / set individual keys
promptgenie config get security.airgap
promptgenie config set security.airgap true
promptgenie config set routing.default ollama
```

---
