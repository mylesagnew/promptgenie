# PromptGenie Roadmap

**Strategic position:** PromptGenie is the secure, terminal-native prompt engineering workbench for developers and DevOps teams. It lets teams author, lint, scan, test, diff, run, benchmark, and govern prompts the same way they manage code.

The winning product lane:

- CLI-first, not web-first
- UNIX-composable, not playground-bound
- SecDevOps-native, not a generic prompt toy
- Local-first where required, cloud-capable where useful
- Built for CI/CD, policy gates, repeatable workflows, and prompt regression testing

Prompt lifecycle: **Author → Render → Lint → Scan → Test → Run → Evaluate → Diff → Gate → Audit**

---

## Delivery Phases

### Phase 1 — Terminal and Pipeline Foundations
*High-leverage, low-risk. Makes PromptGenie feel like a serious daily-use CLI.*

| Feature | Description |
|---|---|
| ~~**Universal stdin/stdout**~~ ✅ | `-` sentinel on `lint`, `scan`, `diff`, `adapt`; `safe_read_text("-")` reads stdin with 1 MB guard; `<stdin>` label in all output formats (Rich, JSON, SARIF); `diff - -` rejected; 641 tests |
| ~~**Stable structured output**~~ ✅ | `schema_version: "1.0"` on all JSON outputs; `diag_console` (stderr) for diagnostics; `is_structured_mode()` suppresses banners; `diff --format json\|yaml\|markdown` |
| ~~**Strict exit code contract**~~ ✅ | `EXIT_*` constants (0–7, 130); `PromptGenieError(code, hint)`; `handle_error()` → stderr; `test` exits 5; SIGINT → 130; all commands updated |
| ~~**Shell completion v2**~~ ✅ | `promptgenie completion install zsh\|bash\|fish`; `show`, `status`, `refresh-cache`; dynamic cache at `~/.cache/promptgenie/completions.json` |
| ~~**`promptgenie doctor`**~~ ✅ | Python version, config, extras, provider keys, Ollama, completion; `--format json` with `schema_version: "1.0"`; remediation hints; exits 1 on hard failures |
| ~~**Side-by-side diff**~~ ✅ | `diff --side-by-side` Rich two-column table; semantic `SequenceMatcher` section pairing; `diff --format json\|yaml\|markdown` (GH-flavoured Markdown with emoji deltas) |
| ~~**Renderer profiles**~~ ✅ | `ColorMode` enum; `--color auto\|always\|never` global flag; `NO_COLOR`/`FORCE_COLOR`; `diag_console` (stderr); `init_renderer()` in CLI group callback |
| ~~**Interactive variable resolver**~~ ✅ | `{{name}}`, `{{name:type:default}}` placeholders; `--var`, `--vars`, `--vars-schema`, `--no-input` on `generate`; env `PG_<NAME>`; type coercion; secret masking; `VarResolutionError` exits 2 |

---

### Phase 2 — PromptSpec and Run Engine ✅
*Turns PromptGenie from a prompt generator into a prompt execution platform.*

| Feature | Description |
|---|---|
| ~~**Declarative PromptSpec**~~ ✅ | `version: 1` YAML/JSON; fields: `name`, `target`, `template`, `mode`, `vars`, `context`, `policy`, `provider`, `output_contract`; JSON Schema at `promptgenie/schemas/promptspec.schema.json`; `spec init`, `spec render`, `spec validate`, `spec schema` |
| ~~**`promptgenie run`**~~ ✅ | End-to-end execution: load spec → resolve vars → build context → lint/scan/policy gate → render → send to provider → stream response → persist run; `--dry-run`, `--stream`, `--require-clean`, `--provider`, `--model`, `--timeout`, `--no-history`, `--tee`, `--format ndjson` |
| ~~**Streaming response mode**~~ ✅ | `asyncio`-based provider stream; NDJSON events: `start`, `token`, `warning`, `tool_call`, `error`, `done`; TTY: raw token stream; non-TTY: NDJSON with `--format ndjson`; `--tee output.md` writes assembled response to file |
| ~~**Variable files and env binding**~~ ✅ | `--vars prod.yaml`, `--var key=val`, `--env-prefix PG_`; `vars list` + `vars inspect --redacted`; secrets masked; resolution source shown per variable |
| ~~**Context builder**~~ ✅ | 8 source types: `file`, `glob`, `stdin`, `env`, `cmd`, `git_diff`, `git_staged`, `url` (policy-gated); `.promptignore`; 4 strategies: `manual`/`newest`/`smallest`/`git-relevant`; SHA-256 + token estimates; `context build --glob "src/**/*.py" --out context.md` |
| ~~**Provider abstraction**~~ ✅ | `BaseProvider` with `async complete()` + `async stream()`; `ProviderCapabilities`; `AnthropicProvider` (SDK or httpx fallback); `OpenAICompatProvider`; config at `~/.config/promptgenie/providers.yaml`; `provider list/add/remove/show/doctor` |
| ~~**Ollama / OpenAI-compatible support**~~ ✅ | `promptgenie provider add ollama --base-url http://localhost:11434/v1 --model llama3 --local`; `provider doctor ollama`; no API key required; LM Studio, LocalAI, vLLM all work via same adapter |

---

### Phase 3 — SecDevOps Guardrails
*Differentiates PromptGenie from generic prompt tools through enterprise-grade security posture.*

| Feature | Description |
|---|---|
| **`promptgenie analyze`** | Aggregate: `lint + scan + policy + custom rules` in one command; unified finding model with `code`, `title`, `severity`, `category`, `location`, `evidence`, `remediation`, `confidence`, `tags`; categories: `prompt-injection`, `data-leakage`, `secret-exposure`, `unsafe-agent-permission`, `destructive-action`, `compliance`, `quality`; SARIF output |
| **Policy-as-code v2** | Extend `policy` command; discovery: `.promptgenie.policy.yaml` → `promptgenie.policy.yaml` → `~/.config/promptgenie/policy.yaml`; `--explain` mode; `external_model_send` gate with `allowed_providers`; policy bundles via rule packs |
| **Data leakage detector** | Expand scanner: JWTs, database URLs, internal hostnames, emails, phone numbers, customer IDs; `promptgenie redact prompt.md --out redacted.md`; pre-send gate in `run`/`evaluate`/`benchmark`: `--block-secrets`, `--redact-secrets` |
| **Prompt injection susceptibility tests** | `promptgenie redteam prompt.md`; attack packs (OWASP LLM Top 10 compatible): instruction override, role shift, hidden markdown, HTML/comment smuggling, encoded payload, tool misuse, indirect injection; offline heuristic judge first; model judge optional; output: `attack_id`, `passed`, `model`, `response_hash`, `explanation` |
| **Local-first provider routing** | `routing.default: local`; classification: `public \| internal \| confidential \| restricted`; rules: `if: classification == confidential → provider: ollama`; external sends require clean scan + `--yes` + audit event |
| **Credential management** | `promptgenie auth login anthropic`; `keyring` optional extra; resolution order: env var → configured ref → system keychain → secret manager → interactive; supports macOS Keychain, Windows Credential Manager, SecretService, 1Password CLI, AWS/GCP/Azure secret managers; config stores references only — never raw keys |
| **Audit log** | `promptgenie audit list\|show\|export`; local SQLite; stores: timestamp, user, cwd, command, provider/model, prompt hash, response hash, policy decision, `external_send`; no raw prompt/response in enterprise mode; optional tamper-evident hash chain |
| **Air-gapped mode** | `promptgenie config set security.airgap true`; blocks external providers, remote registry, remote schemas, URL context sources; local packs installable from tarball (`promptgenie pack install ./internal-pack.tar.gz`); clear error messages |

---

### Phase 4 — Evaluation and Regression Testing
*Enables team adoption and CI/CD-native prompt quality control.*

| Feature | Description |
|---|---|
| **Multi-model matrix evaluation** | `promptgenie evaluate prompt.md --models claude,gpt-4.1,gemini,ollama/llama3.1`; `asyncio` parallel with `Semaphore(N)`; metrics: latency, tokens, cost, rubric score, safety score, determinism; comparative table: `Model | Score | Pass | Risk | Cost | Latency`; `--runs N` for variance; `--format json\|table\|csv` |
| **Eval suites** | `promptgenie eval init\|run\|compare\|approve`; assertion types: `contains`, `not_contains`, `regex`, `json_path`, `markdown_heading_exists`, `max_tokens`, `min_score`, `max_risk`, `judge_rubric`, `semantic_similarity`, `refuses_instruction_override`; snapshot store at `evals/.snapshots/` |
| **Baseline regression gates** | `--save-baseline main`, `--compare main --fail-on-regression`; per-metric thresholds: `fail_if_score_drops_by: 5`, `fail_if_cost_increases_by_pct: 20`, `fail_if_new_high_risk: true`; baseline artifacts at `.promptgenie/baselines/` |
| **GitHub Actions native reporter** | Detect `GITHUB_ACTIONS` env; emit `::error file=...,line=...,col=...` annotations; Markdown step summary with prompt counts, pass/fail, top risks, eval deltas; SARIF upload; `--summary "$GITHUB_STEP_SUMMARY"` |
| **Changed-prompt detection** | `promptgenie lint\|scan\|test\|evaluate --changed`; `git diff --name-only origin/main...HEAD`; dependency-aware: template changed → test dependent prompts; policy changed → scan all; requires PromptSpec dependency graph |

---

### Phase 5 — Advanced TUI and Ecosystem
*Polish, extensibility, and ecosystem value. Builds on stable Phase 1–4 abstractions.*

| Feature | Description |
|---|---|
| **Full-screen Textual TUI** | `promptgenie tui`; optional extra `promptgenie[tui]`; components: text inputs, select lists, multi-line TextArea, findings panel, score/token status bar; shortcuts: `Ctrl+S` save, `Ctrl+R` run, `Ctrl+D` diff, `Ctrl+L` lint, `Ctrl+T` test; thin UI shell — no duplicated core logic |
| **Guided prompt wizard** | `promptgenie wizard`; step-by-step questions: objective, scope, out-of-scope, forbidden, output format, verification, target, context packs; produces both rendered Markdown and reusable `.promptgenie.yaml` spec |
| **Smart command palette** | `promptgenie palette`; Textual fuzzy finder; indexes: commands, templates, profiles, packs, recent files, recent evaluations; keyboard-driven: type "lint auth" → select file → run |
| **Prompt history** | `promptgenie history list\|show\|diff\|replay\|export`; SQLite at `~/.local/share/promptgenie/history.db`; content hashes for deduplication; `--no-history` for privacy-sensitive environments |
| **Watch mode** | `promptgenie watch prompts/ --run lint --run scan`; `watchfiles` optional extra; on-change: re-render → re-lint → re-scan → compact dashboard; debounced; exits non-zero if final state has policy failures |
| **Template command group** | `promptgenie template list\|show\|edit\|new\|validate\|render`; layered locations: built-in → project `.promptgenie/templates/` → user `~/.config/promptgenie/templates/`; `$EDITOR` default; validate before save; dry-run preview |
| **Prompt lockfiles** | `promptgenie lock prompt.yaml`, `--locked`, `--check`; lockfile hashes: template, policy, context files, pack versions, provider model; `--check` fails on stale lockfile; useful for regulated environments |
| **Plugin SDK** | Python entry points: `promptgenie.providers`, `promptgenie.rules`, `promptgenie.renderers`, `promptgenie.context_sources`, `promptgenie.evaluators`; `promptgenie plugin list\|install\|doctor\|scaffold`; compatibility checks and origin display |
| **Signed enterprise packs** | Pack signatures (cosign/minisign); pack diff: `promptgenie pack diff security-baseline@1.1 security-baseline@1.2`; pack promotion: `promote dev baseline --to prod`; pack unit test format with expected findings |

---

## Top 10 Highest-Impact Features

Ordered by development leverage and user adoption impact:

| Rank | Feature | Example |
|---|---|---|
| 1 | ~~**Universal stdin/stdout**~~ ✅ **Done** | `cat prompt.md \| promptgenie lint - --format json \| jq '.issues[]'` |
| 2 | **PromptSpec declarative YAML** | `promptgenie run prompts/auth-review.promptgenie.yaml` |
| 3 | **`promptgenie run` execution engine** | `promptgenie run prompt.yaml --provider ollama --model llama3.1` |
| 4 | **Local-first provider support (Ollama)** | `promptgenie provider add ollama --base-url http://localhost:11434` |
| 5 | **Multi-model matrix evaluation** | `promptgenie evaluate prompt.md --models claude,gpt-4.1,ollama/llama3.1` |
| 6 | **Policy-as-code v2** | `promptgenie policy prompt.md --policy promptgenie.policy.yaml --explain` |
| 7 | **Pre-send secret / data leakage gate** | `promptgenie run prompt.yaml --block-secrets` |
| 8 | **Dynamic context resolver** | `promptgenie run prompt.yaml --context "@cmd:git diff --staged"` |
| 9 | **GitHub Actions annotations and SARIF** | `promptgenie ci run --annotations --sarif promptgenie.sarif` |
| 10 | **Full Textual TUI** | `promptgenie tui --template threat-model --target claude-code` |

---

## Advanced Feature Reference

### Token and Cost Optimizer

```bash
promptgenie tokens prompt.md
promptgenie optimize prompt.md --max-tokens 4000
promptgenie context build --max-tokens 12000 --strategy git-relevant
```

Optimization strategies: remove duplicate context, collapse whitespace, remove low-value sections, prioritize git-changed files, summarize long context. Always show diff before destructive optimization. Requires `promptgenie[tokenizer]`.

---

### Structured Output Contracts

```bash
promptgenie run prompt.yaml --schema output.schema.json --output-mode json
promptgenie validate-output response.json --schema output.schema.json
promptgenie output repair response.txt --schema schema.json
```

PromptSpec:

```yaml
output_contract:
  type: json
  schema: ./schemas/finding.schema.json
  strict: true
```

Use native structured output where available; otherwise inject schema into prompt and validate post-parse. Repair mode coerces malformed output and marks repaired fields.

---

### Prompt Dependency Graph

```bash
promptgenie graph workflows/secure-login.workflow.yaml --format mermaid
promptgenie graph --format dot
promptgenie graph --format json
```

Nodes: PromptSpec, Template, Context pack, Policy, Provider/model, Eval suite. Used in CI reports and dependency-aware `--changed` filtering.

---

### `promptgenie fmt`

```bash
promptgenie fmt prompts/*.md
promptgenie fmt prompts/*.promptgenie.yaml
promptgenie fmt --check prompts/
```

Markdown: normalize headings, enforce section order, trim trailing whitespace, ensure final newline. YAML: stable key order, comment preservation via `ruamel.yaml`. `--check` mode exits 1 if formatting would change (CI-safe).

---

### `promptgenie make` — Batch Runner

```yaml
# promptgenie.make.yaml
tasks:
  lint:
    run: promptgenie lint prompts/**/*.md
  scan:
    run: promptgenie scan prompts/**/*.md
  test:
    run: promptgenie test tests/**/*.prompt-test.yaml
  ci:
    needs: [lint, scan, test]
```

```bash
promptgenie make --target ci --changed --parallel 4
```

Simple YAML task graph; dependency ordering; changed-file filtering; parallel execution; compatible with Make, just, Taskfile, and CI scripts.

---

### Provider Routing Policy

```yaml
# .promptgenie.policy.yaml
routing:
  default: local
  rules:
    - if: contains_secrets
      provider: ollama
    - if: classification == confidential
      provider: localai
    - if: classification == public
      provider: anthropic
```

Classification can be manually declared in PromptSpec, inferred by the scanner, or enforced by policy. External sends require clean scan + `allowed_providers` match + `--yes` in non-interactive mode + audit log event.

---

### Shell Completion Reference

```bash
promptgenie completion install zsh    # install into ~/.zshrc
promptgenie completion install bash   # install into ~/.bashrc
promptgenie completion install fish   # install into ~/.config/fish/
promptgenie completion print zsh      # print to stdout for manual install
promptgenie completion doctor         # verify completion is active
```

Dynamic completions for `--template`, `--target`, `--provider`, `--model`, context pack names, PromptSpec files, test files, workflow files, and template variable names for the selected template.

---

## Key Architecture Principles

1. **TUI is a thin shell.** The Textual TUI calls existing core services — it does not duplicate generate/lint/scan/test logic.
2. **Stdin/stdout discipline.** Machine-readable output → stdout. Warnings, progress, spinners → stderr. Rich panels only when stdout is a TTY.
3. **Security-by-default.** LLM analysis is opt-in. External sends require clean scan. Credential management uses keyring, never flat config. Air-gap mode blocks all outbound calls.
4. **Local-first.** Ollama and OpenAI-compatible local providers are first-class. Offline mode should work for lint, scan, test, evaluate, and audit without any network access.
5. **Composable, not monolithic.** Every command should work in isolation, pipe cleanly, and produce stable structured output suitable for downstream tools.
6. **Provider-agnostic.** The core engine should never hardcode a specific LLM provider. The `Provider` protocol handles all provider-specific behavior.
7. **Reproducible.** Prompt lockfiles, content hashing, and baseline snapshots make prompt workflows as reproducible as software builds.

---

## Optional Extras Plan

| Extra | Installs | Enables |
|---|---|---|
| `benchmark` | `anthropic` | `promptgenie benchmark` |
| `tokenizer` | `tiktoken` | Accurate token counts |
| `llm` | `openai` | `promptgenie scan --llm` |
| `tui` | `textual` | `promptgenie tui`, `palette`, `wizard` |
| `watch` | `watchfiles` | `promptgenie watch` |
| `secrets` | `keyring` | `promptgenie auth login` |
| `semantic-diff` | `rapidfuzz` | `promptgenie diff --semantic` |

Base install (`pip install promptgenie`) requires only `click`, `rich`, and `pyyaml` — no HTTP clients, no API keys, no heavy dependencies.

---

*This roadmap is reviewed and updated as features ship. See [CHANGELOG.md](CHANGELOG.md) for shipped items and [SECURITY.md](SECURITY.md) for security policy.*
