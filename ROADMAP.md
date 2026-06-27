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

### Phase 1 — Terminal and Pipeline Foundations ✅
*High-leverage, low-risk. Makes PromptGenie feel like a serious daily-use CLI.*

| Feature | Description |
|---|---|
| ~~**Universal stdin/stdout**~~ ✅ | `-` sentinel on `lint`, `scan`, `diff`, `adapt`; `safe_read_text("-")` reads stdin with 1 MB guard; `<stdin>` label in all output formats (Rich, JSON, SARIF); `diff - -` rejected; 641 tests |
| ~~**Stable structured output**~~ ✅ | `schema_version: "1.0"` on all JSON outputs; `diag_console` (stderr) for diagnostics; `is_structured_mode()` suppresses banners; `diff --format json\|yaml\|markdown` |
| ~~**Strict exit code contract**~~ ✅ | `EXIT_*` constants (0–8, 130); `PromptGenieError(code, hint)`; `handle_error()` → stderr; `test` exits 5; `regression` exits 8; SIGINT → 130; all commands updated |
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

### Phase 3 — SecDevOps Guardrails ✅
*Differentiates PromptGenie from generic prompt tools through enterprise-grade security posture.*

| Feature | Description |
|---|---|
| ~~**`promptgenie analyze`**~~ ✅ | Aggregate: `lint + scan + policy + custom rules` in one command; unified finding model with `code`, `title`, `severity`, `category`, `location`, `evidence`, `remediation`, `confidence`, `tags`; categories: `prompt-injection`, `data-leakage`, `secret-exposure`, `unsafe-agent-permission`, `destructive-action`, `compliance`, `quality`; SARIF output |
| ~~**Policy-as-code v2**~~ ✅ | `promptgenie/core/policy_engine.py`; discovery: `.promptgenie.policy.yaml` → `promptgenie.policy.yaml` → `~/.config/promptgenie/policy.yaml`; `--explain` mode; `external_model_send` gate with `allowed_providers` and `block_on_classification`; `PolicyEvaluation` with per-rule violation detail |
| ~~**Data leakage detector**~~ ✅ | Expanded scanner: `LEAK_JWT`, `LEAK_DB_URL`, `LEAK_INTERNAL_HOST`, `LEAK_EMAIL`, `LEAK_PHONE`, `LEAK_CC`, `LEAK_SSN`, `LEAK_IPADDR`, `LEAK_BEARER`; `promptgenie redact prompt.md --out redacted.md`; `--diff`, `--dry-run`, `--categories`, `--format json`; `[REDACTED:LABEL]` placeholders |
| ~~**Prompt injection susceptibility tests**~~ ✅ | `promptgenie redteam prompt.md`; 13 attack packs (OWASP LLM Top 10 aligned): instruction override, role shift, indirect injection, HTML smuggling, base64/Unicode obfuscation, system prompt extraction, tool misuse, PII disclosure; offline heuristic judge; `--categories`, `--attacks`, `--list-attacks`, `--fail-on-susceptible`; output: `attack_id`, `susceptible`, `confidence`, `payload_hash`, `explanation` |
| ~~**Local-first provider routing**~~ ✅ | `RoutingConfig` in config; `routing.default: local`; rules: `if: classification == confidential → provider: ollama`, `if: contains_secrets → provider: ollama`, `if: "*" → provider: anthropic`; `RoutingConfig.resolve()` evaluates rules in order |
| ~~**Credential management**~~ ✅ | `promptgenie auth login/logout/status`; `--source keyring\|env\|1password\|aws-ssm\|gcp-secret\|azure-keyvault`; `--ref` for external secret manager paths; `get_credential()` resolves `ref:` pointers at runtime; supports macOS Keychain, Windows Credential Manager, SecretService; fallback to providers.yaml |
| ~~**Audit log**~~ ✅ | `promptgenie audit list\|show\|export\|verify`; local SQLite at `~/.local/share/promptgenie/audit.db`; tamper-evident SHA-256 hash chain; export to JSON/CSV/NDJSON; `audit verify` checks chain integrity |
| ~~**Air-gapped mode**~~ ✅ | `promptgenie config set security.airgap true`; `SecurityConfig` in config; enforced in `providers.get_provider()` — blocks non-local providers; `promptgenie config show/set/get` command group |

---

### Phase 4 — Evaluation and Regression Testing ✅
*Enables team adoption and CI/CD-native prompt quality control.*

| Feature | Description |
|---|---|
| ~~**Multi-model matrix evaluation**~~ ✅ | `promptgenie evaluate prompt.md --models claude,gpt-4.1,gemini,ollama/llama3.1`; `asyncio` parallel with `Semaphore(N)`; per-model metrics: latency (ms), input/output tokens, cost (USD), rubric score (0–100 heuristic), safety score, determinism (σ across N runs); `--format rich\|json\|sarif`; `--summary` |
| ~~**Eval suites**~~ ✅ | `promptgenie eval init\|run\|compare\|approve`; 11 assertion types: `contains`, `not_contains`, `regex_match`, `regex_not_match`, `json_path`, `markdown_heading_exists`, `max_risk`, `word_count_min`, `word_count_max`, `semantic_similarity` (TF-IDF cosine; no ML dep), `judge_rubric`, `refuses_instruction_override`; snapshot store at `evals/.snapshots/`; `--dry-run` for offline assertion testing |
| ~~**Baseline regression gates**~~ ✅ | `--save-baseline NAME`, `--compare NAME --fail-on-regression`; exits `EXIT_REGRESSION = 8` on breach; per-metric thresholds: `--score-drop-threshold` (default 5 pts), `--cost-increase-pct` (default 20%), `--latency-increase-pct`, `--no-high-risk-gate`; artefacts at `.promptgenie/baselines/<name>.json` |
| ~~**GitHub Actions native reporter**~~ ✅ | Auto-detected via `GITHUB_ACTIONS=true`; `::error file=...,line=...,col=...` and `::warning` annotations for findings and regressions; Markdown step summary appended to `$GITHUB_STEP_SUMMARY`; SARIF 2.1.0 output via `eval_results_to_sarif()`; wired into `evaluate`, `eval run`, and `eval compare` |
| ~~**Changed-prompt detection**~~ ✅ | `--changed` flag on `evaluate` and `eval run`; `git diff --name-only <base-ref>...HEAD`; dependency-aware expansion: policy file changed → all specs affected; template changed → all dependent specs; `--base-ref` (default: `origin/main`) |

---

### Phase 5 — Advanced TUI and Ecosystem ✅
*Polish, extensibility, and ecosystem value. Builds on stable Phase 1–4 abstractions.*

| Feature | Description |
|---|---|
| ~~**Full-screen Textual TUI**~~ ✅ | `promptgenie tui [FILE]`; optional extra `promptgenie[tui]`; layout: file-tree navigator (30%), Markdown TextArea (1fr), live findings panel (10 lines), score/token/provider status bar; bindings: `Ctrl+S` save, `Ctrl+R` run, `Ctrl+L` lint, `Ctrl+D` diff, `Ctrl+T` eval-suite test, `Ctrl+Q` quit; graceful degradation when `textual` is absent |
| ~~**Guided prompt wizard**~~ ✅ | `promptgenie wizard`; 8-step Q&A (objective, scope, out-of-scope, forbidden, output format, verification, target profile, context packs); produces rendered Markdown + optional PromptSpec YAML; `--out`, `--spec-out`, `--no-spec`; no Textual dependency required |
| ~~**Smart command palette**~~ ✅ | `promptgenie palette`; Textual fuzzy finder across all commands, templates, context packs, and recent history entries; readline fallback when `textual` absent; `--print-only` emits selected CLI command for shell piping (`eval $(promptgenie palette --print-only)`) |
| ~~**Prompt history**~~ ✅ | `promptgenie history list\|show\|diff\|replay\|export\|clear`; SQLite at `~/.local/share/promptgenie/history.db`; SHA-256 content-hash deduplication; sub-commands: `list` (--limit, --provider, --status, --spec, --search, --format), `show` (run-ID prefix matching), `diff` (unified diff between two responses), `replay` (--dry-run), `export` (json/csv/ndjson), `clear` |
| ~~**Watch mode**~~ ✅ | `promptgenie watch <paths> --run lint\|scan\|policy`; `watchfiles` optional extra (`promptgenie[watch]`) with polling fallback; `--debounce` (ms); `--fail-on-policy`; debounced Rich `Live` dashboard showing pass/fail per file per pipeline |
| ~~**Template command group**~~ ✅ | `promptgenie template list\|show\|render\|validate\|new\|edit`; layered resolution: project (`.promptgenie/templates/`) → user (`~/.config/promptgenie/templates/`) → built-in; higher-priority layers shadow by ID; `$EDITOR` integration; re-validates after `edit`; `--format json` on `list` and `show` |
| ~~**Prompt lockfiles**~~ ✅ | `promptgenie lock prompt.yaml` creates `<spec>.lock` (SHA-256 hashes of spec, template, policy, context sources, provider/model); `--check` detects drift (exits 1); `--strict` also fails on missing optional files; `--format json` for CI; safe to commit — contains only paths and digests, never content |
| ~~**Plugin SDK**~~ ✅ | Python `importlib.metadata` entry points across 5 groups: `promptgenie.providers`, `promptgenie.rules`, `promptgenie.renderers`, `promptgenie.context_sources`, `promptgenie.evaluators`; `plugin list` (--format json), `plugin doctor` (compat checks), `plugin scaffold NAME --group GROUP` (writes stub `.py`), `plugin install` (thin `pip install` wrapper) |
| ~~**Signed enterprise packs**~~ ✅ | `pack verify <pack> --pubkey KEY --method minisign\|cosign`; `pack diff old.yaml new.yaml` (added/removed/modified rule IDs); `pack promote <name> --from dev --to staging` (copies between `.promptgenie/pack-envs/<env>/` slots); `pack test pack.yaml tests.yaml` (declarative YAML unit tests; exits 1 on failures) |

---

### Phase 6 — Governance, SSO, and Cloud Sync
*Enterprise hardening: team-scale policy enforcement, identity-aware access, and centralised prompt management.*

| Feature | Description |
|---|---|
| **Team policy server** | Central `.promptgenie-policy` server; policies fetched on every run; org-wide `disabled_rules`, allowlists, routing rules, approved provider list; policy version pinned in lockfile |
| **SSO / OIDC credential binding** | `promptgenie auth login --sso`; OIDC device flow; per-user audit attribution; credential scoped to authenticated identity; `PROMPTGENIE_TOKEN` env var for CI |
| **Prompt registry (self-hosted or cloud)** | 🟡 **Phase A + B.1 shipped.** *Local store:* `push/pull/list/tags/show/verify/rm/prune/search`; content-addressable OCI-inspired store; artifact = spec + template + policy + context + schema under one signed manifest; fail-closed digest verification; minisign/cosign signing with `--require-signed`; digest pins (`@sha256:`); audit; path-traversal-guarded pull. *Remote (B.1):* `--remote host[/ns]` push/pull/show/verify/tags against any OCI registry (ghcr.io/Zot/Harbor); OCI image manifests; **blob dedup on push**; client-side digest verification (untrusted server); cosign-style `.sig` signatures; `registry login/logout` (keyring + CI env); HTTPS-only + air-gap gate; `httpx` via `promptgenie[registry-remote]`. **Deferred — B.2:** SSO/OIDC device-flow login + per-user attribution (the SSO roadmap item). See [docs/registry-design.md](docs/registry-design.md). |
| **Remote eval runners** | Offload matrix evaluations to a cloud runner pool; results streamed back; cost and latency budgets enforced server-side; results stored in registry alongside the prompt |
| **VSCode extension — Phase 2** | Inline eval results, baseline delta badge, TUI launcher from the editor title bar; history sidebar; lockfile status indicator |
| ~~**`promptgenie fmt`**~~ ✅ | Normalise Markdown prompt files and PromptSpec YAML: ATX heading normalisation, blank-line structure around headings, trailing-whitespace trim, single final newline, canonical PromptSpec key sort; fence-aware (code blocks preserved byte-for-byte); comment-preserving YAML reorder via optional `ruamel.yaml` (`promptgenie[fmt]`), comment-safe fallback otherwise; in-place by default, `--check` exits 1 if formatting would change (CI-safe), `--diff`, `--format json`, `--lang`; idempotent |
| ~~**`promptgenie make`**~~ ✅ | YAML task graph (`promptgenie.make.yaml`): `lint`/`scan`/`test`/`evaluate` and any shell command, wired with `needs:`; topological ordering; `--changed` filtering on per-task `inputs:` globs (aggregators run only dirty sub-tasks); `--parallel N`; fail-fast with `--keep-going`; `--dry-run`, `--list`, `--format json`; multi-command tasks; cycle detection; dependency-free; compatible with Make, just, Taskfile |
| **`promptgenie make`** | YAML task graph (`promptgenie.make.yaml`): `lint`, `scan`, `test`, `evaluate`; `--changed` filtering; `--parallel N`; compatible with Make, just, Taskfile |

---

## Top 10 Highest-Impact Features

Ordered by development leverage and user adoption impact:

| Rank | Feature | Status | Example |
|---|---|---|---|
| 1 | ~~**Universal stdin/stdout**~~ | ✅ Done | `cat prompt.md \| promptgenie lint - --format json \| jq '.issues[]'` |
| 2 | ~~**PromptSpec declarative YAML**~~ | ✅ Done | `promptgenie run prompts/auth-review.promptgenie.yaml` |
| 3 | ~~**`promptgenie run` execution engine**~~ | ✅ Done | `promptgenie run prompt.yaml --provider ollama --model llama3.1` |
| 4 | ~~**Local-first provider support (Ollama)**~~ | ✅ Done | `promptgenie provider add ollama --base-url http://localhost:11434` |
| 5 | ~~**Multi-model matrix evaluation**~~ | ✅ Done | `promptgenie evaluate prompt.md --models claude,gpt-4.1,ollama/llama3.1` |
| 6 | ~~**Policy-as-code v2**~~ | ✅ Done | `promptgenie policy prompt.md --policy promptgenie.policy.yaml --explain` |
| 7 | ~~**Pre-send secret / data leakage gate**~~ | ✅ Done | `promptgenie run prompt.yaml --block-secrets` |
| 8 | ~~**Dynamic context resolver**~~ | ✅ Done | `promptgenie context build --git-diff --glob "src/**/*.py"` |
| 9 | ~~**GitHub Actions annotations and SARIF**~~ | ✅ Done | Auto-detected; `::error` annotations + step summary + SARIF upload |
| 10 | ~~**Full Textual TUI**~~ | ✅ Done | `promptgenie tui --provider claude prompts/auth.md` |

**All 10 highest-impact features shipped.** v1.7.0 adds the workspace schema, `WorkspaceConfig`/`DefaultsConfig` parsing, `config validate`, and `config init`. Next focus: team-scale governance (Phase 6).

---

## Advanced Feature Reference

### Token and Cost Optimizer

```bash
promptgenie compress prompt.md                      # ✅ shipped
promptgenie optimize prompt.md --max-tokens 4000    # ✅ shipped (alias of compress)
promptgenie tokens prompt.md                         # ✅ shipped (read-only inspector)
promptgenie context build --max-tokens 12000 --strategy git-relevant  # ✅ shipped
```

**Shipped:** `promptgenie compress` / `optimize` — a native, dependency-free compression engine (`promptgenie/core/compressor.py`) inspired by [headroom](https://github.com/headroomlabs-ai/headroom). Content-routed, fence-aware techniques in two tiers: lossless **default** (`trim-trailing-ws`, `collapse-blank-lines`, `json-compact`) and lossy **aggressive** (`strip-html-comments`, `collapse-spaces`, `dedupe-log-lines`). `--max-tokens` budget, `--diff`/`--dry-run`, `--format json|yaml`. Accurate token counts use `tiktoken` when installed (`promptgenie[tokenizer]`), falling back to a `len/4` estimate.

**Shipped:** `promptgenie tokens` — the read-only companion to `compress`: reports a prompt's token count and the *potential* savings of each compression technique (applied individually) plus the combined default-tier and all-tier totals, without modifying anything. `--format text|json|yaml`.

**Shipped:** context-builder auto-compression — `run` and `context build` now accept `--compress-context` / `--compress` (safe tier) and `--compress-aggressive`, running the compressor over the *assembled* context before it is sent. `build_context` returns the savings on `ContextManifest.compression` (before/after tokens, per-technique breakdown), surfaced in `--show-context`, the build report, and `--format json|yaml`.

**Shipped:** summarisation — heuristic, dependency-free low-value-section removal (`promptgenie compress --summarise`). Splits the document into heading-delimited sections and drops low-value ones (examples, changelog, appendix, log dumps) together with their subsections. Without a budget it removes only low-value sections; with `--max-tokens` it additionally drops other non-protected sections (largest first) until the document fits. Protected sections (objective, scope, requirements, output format, guardrails…) and the preamble are never dropped; headings inside fenced code are ignored. Dropped sections are reported on `CompressResult.dropped_sections` and in `--format json`.

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

**Shipped:** structured output contracts (`promptgenie/core/output_contract.py`). `promptgenie validate-output FILE --schema S` validates a response (file/stdin) against a JSON Schema; `promptgenie output repair FILE --schema S` extracts JSON embedded in prose, coerces scalar types, fills missing required fields from their `default`/type, and re-validates; `promptgenie run --schema S --output-mode json` validates the live response against `--schema` (or the spec's `output_contract.schema`, inline or a file path) and exits 1 if it does not conform. Validation uses the optional `jsonschema` library when installed (`pip install promptgenie[schema]`) and otherwise a built-in subset validator (`type`, `required`, `properties`, `items`, `enum`, `additionalProperties`, `minimum`/`maximum`, `minLength`/`maxLength`, `minItems`/`maxItems`, `pattern`) — base install stays dependency-free. 36 tests in `tests/test_output_contract.py`.

---

### Prompt Dependency Graph

```bash
promptgenie graph workflows/secure-login.workflow.yaml --format mermaid
promptgenie graph --format dot
promptgenie graph --format json
```

Nodes: PromptSpec, Template, Context pack, Policy, Provider/model, Eval suite. Used in CI reports and dependency-aware `--changed` filtering.

**Shipped:** `promptgenie graph` (`promptgenie/core/graph.py`, `promptgenie/commands/graph_cmd.py`). Builds a typed node/edge graph — `spec`, `workflow`, `step`, `template`, `target`, `provider`, `model`, `policy`, `context`, `schema` — from one or more spec/workflow files, or by discovering every recognisable spec/workflow under `--root`. Shared dependencies (a provider/template/policy used by many specs) de-duplicate to a single node; workflow `depends_on` becomes step→step edges. Renders to `--format mermaid|dot|json`; `--out FILE` to write. Dependency-free. 15 tests in `tests/test_graph.py`.

---

### `promptgenie fmt`

```bash
promptgenie fmt prompts/*.md
promptgenie fmt prompts/*.promptgenie.yaml
promptgenie fmt --check prompts/         # CI-safe: exits 1 if reformatting needed
promptgenie fmt --diff prompt.md         # unified diff, no write
cat prompt.md | promptgenie fmt -        # stdin → stdout
```

Markdown: ATX heading normalisation (single space after `#`, no closing hashes), one blank line around headings, trailing-whitespace trim, blank-line-run collapse, single final newline. Fenced ```code``` blocks are preserved byte-for-byte. YAML: stable canonical key order (matching the `PromptSpec` field order, top-level + `output_contract`/`run`) plus the same whitespace normalisation; comments preserved via `ruamel.yaml` (`promptgenie[fmt]`), with a comment-safe fallback (commented files keep their key order) so the base install stays dependency-free. File arguments format in place (atomic, only changed files touched); `--check` exits 1 if formatting would change (CI-safe); `--diff` prints a unified diff; `--format json` emits a machine-readable summary; `--lang auto|markdown|yaml` forces the type. Deterministic and idempotent.

**Shipped** (`promptgenie/core/formatter.py`, `promptgenie/commands/fmt_cmd.py`). 34 tests in `tests/test_formatter.py`.

---

### `promptgenie make` — Batch Runner

```yaml
# promptgenie.make.yaml
tasks:
  lint:
    run: promptgenie lint prompts/**/*.md
    inputs: ["prompts/**/*.md"]
  scan:
    run: promptgenie scan prompts/**/*.md
    inputs: ["prompts/**/*.md"]
  test:
    run: promptgenie test tests/**/*.prompt-test.yaml
    inputs: ["tests/**", "prompts/**"]
  ci:
    needs: [lint, scan, test]
```

```bash
promptgenie make                              # run every task
promptgenie make ci                           # run 'ci' and its dependencies
promptgenie make --target ci --changed --parallel 4
promptgenie make ci --dry-run                 # show the plan
promptgenie make --list                       # list tasks
```

Simple YAML task graph; topological ordering; changed-file filtering on per-task `inputs:` globs (`**` supported; aggregators run only the dirty sub-tasks); bounded `--parallel N`; fail-fast by default with `--keep-going`; `--dry-run`, `--list`, `--format json`. A task's `run:` may be a single command or a list (fail-fast within the task). Compatible with Make, just, Taskfile, and CI scripts. `shell=True` execution is scoped to the author-trusted, repo-committed makefile (same trust model as a Makefile).

**Shipped** (`promptgenie/core/make.py`, `promptgenie/commands/make_cmd.py`). 32 tests in `tests/test_make.py`.

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
8. **Extensible by default.** The plugin SDK and entry-point system let teams add providers, rules, renderers, and evaluators without forking the codebase.

---

## Optional Extras Plan

| Extra | Installs | Enables |
|---|---|---|
| `benchmark` | `anthropic` | `promptgenie benchmark` |
| `tokenizer` | `tiktoken` | Accurate token counts |
| `providers` | `httpx` + `anthropic` | `promptgenie run` (full provider support) |
| `tui` | `textual>=0.50` | `promptgenie tui`, `promptgenie palette` |
| `watch` | `watchfiles>=0.21` | `promptgenie watch` (fast inotify/FSEvents mode) |
| `schema` | `jsonschema>=4.0` | Full JSON Schema validation for `validate-output` / `output repair` / `run --schema` (built-in subset validator used otherwise) |
| `llm` | `openai` | `promptgenie scan --llm` |
| `secrets` | `keyring` | `promptgenie auth login` (keyring backend) |
| `semantic-diff` | `rapidfuzz` | `promptgenie diff --semantic` |
| `fmt` | `ruamel.yaml>=0.18` | Comment-preserving YAML key sort for `promptgenie fmt` (whitespace + Markdown formatting work without it) |

Base install (`pip install promptgenie`) requires only `click`, `rich`, and `pyyaml` — no HTTP clients, no API keys, no heavy dependencies.

---

## Current Status

| Phase | Status | Tests added | Cumulative tests |
|---|---|---|---|
| Phase 1 — Terminal and Pipeline Foundations | ✅ Shipped (v1.1.0) | 128 | 765 |
| Phase 2 — PromptSpec and Run Engine | ✅ Shipped (v1.2.0) | 93 | 858 |
| Security patch — SSRF / injection / secrets gate | ✅ Shipped (v1.2.1) | 39 | — |
| Security patch — DNS rebinding / VS Code binary / mypy | ✅ Shipped (v1.2.2) | 11 | — |
| Security patch — allowlist bypass / spec trust / IP pinning | ✅ Shipped (v1.2.3) | 32 | — |
| Security patch — URL gate bypass / provider TLS / extension fail-closed | ✅ Shipped (v1.2.4) | 15 | — |
| Phase 3 — SecDevOps Guardrails | ✅ Shipped (v1.3.0) | 71 | — |
| Phase 4 — Evaluation and Regression Testing | ✅ Shipped (v1.4.0) | 77 | — |
| Phase 5 — Advanced TUI and Ecosystem | ✅ Shipped (v1.5.0) | 81 | — |
| v1.6.0 — Internal Event Model + Policy Hardening | ✅ Shipped (v1.6.0) | 110 | — |
| v1.7.0 — Workspace Schema + Config Validation | ✅ Shipped (v1.7.0) | 70 | — |
| Native token compression (`compress`/`optimize`) | ✅ Shipped (Unreleased) | 30 | — |
| NousResearch Hermes integration (profile + provider) | ✅ Shipped (Unreleased) | 11 | — |
| Security hardening (history privacy, extension bound, SBOM attest, version-drift + gitleaks CI, threat model) | ✅ Shipped (Unreleased) | 50 | — |
| Coverage uplift — async-provider harness + command tests (~75%→~82%) | ✅ Shipped (Unreleased) | ~130 | 1541 |
| `promptgenie tokens` — read-only savings inspector | ✅ Shipped (Unreleased) | 6 | — |
| Pack fixes (`pack list` None crash, `pack init` location) | ✅ Shipped (Unreleased) | 10 | — |
| Coverage uplift — Textual TUI + benchmark command (~82%→~83%) | ✅ Shipped (Unreleased) | ~20 | **1571** |
| `promptgenie fmt` — canonical prompt + PromptSpec formatter (Phase 6) | ✅ Shipped (Unreleased) | 34 | — |
| `promptgenie make` — YAML task-graph batch runner (Phase 6) | ✅ Shipped (Unreleased) | 32 | — |
| Prompt registry — Phase A, local-first (Phase 6) | ✅ Shipped (Unreleased) | 41 | — |
| Prompt registry — Phase B.1, remote OCI backend (Phase 6) | ✅ Shipped (Unreleased) | 18 | — |
| Phase 6 — Governance, SSO, and Cloud Sync (remaining) | 🔲 Planned | — | — |

*This roadmap is reviewed and updated as features ship. See [CHANGELOG.md](CHANGELOG.md) for shipped items and [SECURITY.md](SECURITY.md) for security policy.*
