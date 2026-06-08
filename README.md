<p align="center">
  <img src="assets/logo.png" alt="PromptGenie" width="600" />
</p>

# PromptGenie

**Secure prompt engineering for AI agents and engineering teams.**

PromptGenie is a CLI that turns rough task descriptions into optimised, tool-specific, security-checked prompts — with a built-in linter, security scanner, diff engine, test runner, model benchmarker, context pack system, workflow engine, CI integration, quality scoring, and token estimation.

---

## Why

Most prompt engineering is done by hand, rewritten constantly, and never tested. Prompts for agentic tools (Claude Code, Cursor, Devin) are especially risky: a vague scope or missing stop condition can cause scope creep, destructive edits, or unintended deployments.

PromptGenie makes prompts:

- **Structured** — section-by-section output matched to the target tool's requirements
- **Linted** — catches vague verbs, missing scope, broad tasks, and agentic risks before you send
- **Scanned** — flags heuristic patterns consistent with secrets, prompt injection, and unsafe agent permissions
- **Diffed** — compare two versions with token delta, score delta, section changes, and risk changes
- **Tested** — declarative unit tests assert quality, safety, structure, and content before you ship
- **Benchmarked** — run prompts against real Claude models and score responses across 6 rubric dimensions
- **Context-aware** — reusable project context packs inject stack, architecture, pitfalls, and style into every prompt
- **Workflow-driven** — break complex tasks into staged prompt chains with approval gates, handoffs, and per-step scope locks
- **CI-integrated** — GitHub Actions workflow and pre-commit hooks keep bad prompts out of your repo
- **Machine-readable** — `--format json` and `--format sarif` on every lint and scan for CI pipelines and GitHub code scanning
- **Scored** — rates every prompt across 7 quality dimensions
- **Repeatable** — YAML model profiles, templates, and context packs versioned alongside your code

---

## Quickstart

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Generate a security-checked prompt for Claude Code
promptgenie generate "review this repo for security issues" --target claude-code

# Scan a prompt file for secrets and injection risks
promptgenie scan examples/auth-refactor.md

# Lint a prompt for quality issues
promptgenie lint examples/auth-refactor.md

# Launch the guided interactive menu
promptgenie interactive
```

Expected output: a structured, linted, scored prompt ready to paste into your AI tool.

---

## Demo

**Generate a structured, scored prompt:**

```
$ promptgenie generate "review this repo for security issues" --target claude-code

╭─ Generated Prompt  target: claude-code  template: agentic-task  mode: standard ─╮
│ # Prompt for Claude Code                                                         │
│                                                                                  │
│ ## Objective                                                                     │
│ review this repo for security issues                                             │
│                                                                                  │
│ ## Scope                                                                         │
│ Work only within the explicitly listed files or directories.                     │
│ Do not modify files outside this scope without asking first.                     │
│                                                                                  │
│ ## Stop Conditions                                                               │
│ Stop and ask for approval if:                                                    │
│ - Any file outside the defined scope needs to be modified                        │
│ - A new dependency would be added                                                │
│ - A database schema change is required                                           │
│ - Tests fail and the fix is non-obvious                                          │
│ - The task would require a deployment                                            │
│                                                                                  │
│ ## Output Format                                                                 │
│ Show diffs for each changed file.                                                │
│ Run tests and report results.                                                    │
│ Summarise what changed and why.                                                  │
│                                                                                  │
│ ## Acceptance Criteria                                                           │
│ Done when all objectives are met, output matches the requested format,           │
│ and no forbidden actions were taken.                                             │
╰──────────────────────────────────────────────────────────────────────────────────╯
╭──────────────────────── Prompt Quality Score ──────────────────────────────────╮
│                                                                                │
│   Target Fit            83    Task Clarity          90                         │
│   Context Sufficiency   75    Output Contract       90                         │
│   Safety Controls       82    Token Efficiency      95                         │
│   Testability           90                                                     │
│                                                                                │
│   Overall           86/100   Token estimate        150                         │
│                                                                                │
╰────────────────────────────────────────────────────────────────────────────────╯
```

**Scan a prompt for static prompt-risk patterns:**

```
$ promptgenie scan examples/auth-refactor.md

╭──────────── Security Scan  Risk: HIGH  examples/auth-refactor.md ────────────╮
│ [HIGH] [PERM_006] Unrestricted package installation.                         │
│   → Restrict agent permissions to minimum required scope.                    │
│     Add explicit approval gates.                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

> **Scanner scope:** `scan` is a regex/heuristic tripwire with Unicode normalization (NFKC). It catches obvious prompt-injection vocabulary, hardcoded secrets, unsafe agent permission patterns, split/multiline overrides, HTML and block-comment smuggling, base64-encoded payloads (≥40 chars, >70% printable), and fullwidth Unicode obfuscation. It does **not** catch within-word character splits, non-NFKC Unicode homoglyphs (e.g. Turkish ı), synonym substitution, or indirect reference attacks. See `tests/test_scanner_adversarial.py` for a full list of documented detection gaps.

**Lint a prompt for quality issues:**

```
$ promptgenie lint examples/auth-refactor.md

╭────────────── Lint Results  80/100  examples/auth-refactor.md ───────────────╮
│ [HIGH] [AGENT_004] Allows unrestricted package installation.                 │
│   → Add explicit constraints and approval gates.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

**Validate all built-in profiles against the schema:**

```
$ promptgenie validate-profiles

Validating 5 profile(s) in promptgenie/profiles

✓  [profile] chatgpt.yaml
✓  [profile] claude-code.yaml
✓  [profile] claude.yaml
✓  [profile] cursor.yaml
✓  [profile] gemini.yaml

All 5 file(s) valid.
```

**Validate everything at once (profiles, templates, context packs):**

```
$ promptgenie validate --all

✓  [profile]      chatgpt.yaml
✓  [profile]      claude-code.yaml
✓  [profile]      claude.yaml
✓  [profile]      cursor.yaml
✓  [profile]      gemini.yaml
✓  [template]     cyber_templates.yaml  (7 templates)
✓  [context-pack] cyber-security-team.yaml
✓  [context-pack] django-rest-api.yaml
✓  [context-pack] react-supabase-app.yaml

All 15 file(s) valid.
```

Errors fail CI (exit 1). Warnings are advisory (exit 0). Use `--no-warnings` to suppress them.

---

## Install

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Optional extras:

| Extra | What it adds | Install |
|---|---|---|
| `benchmark` | `anthropic` SDK — required for `promptgenie benchmark` | `pip install "promptgenie[benchmark]"` |
| `tokenizer` | `tiktoken` — accurate token counts (falls back to `len/4` without it) | `pip install "promptgenie[tokenizer]"` |

### Docker

```bash
# Build
docker build -t promptgenie .

# Run any command
docker run --rm promptgenie generate "review this repo for security issues" --target claude-code

# Benchmark (requires API key)
docker run --rm -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v "$PWD":/prompts promptgenie benchmark /prompts/my-prompt.md --yes
```

The image runs as a non-root user (`promptgenie`, uid 1001). Mount a local directory with `-v` to read and write prompt files.

---

## Commands

| Command | Description |
|---|---|
| `generate` | Build an optimised prompt from a rough task description |
| `lint` | Check a prompt file for quality and structural issues |
| `scan` | Scan a prompt file for security risks |
| `policy` | CI policy gate — fail the build if findings breach configurable thresholds; outputs text, JSON, or SARIF |
| `diff` | Compare two prompt versions — token, score, section, and risk delta |
| `adapt` | Translate a prompt from one target profile to another |
| `test` | Run a declarative prompt test suite |
| `benchmark` | Run a prompt against a Claude model and score the output |
| `workflow` | Generate a staged prompt chain from a `.workflow.yaml` file |
| `pack list` | List available context packs |
| `pack show` | Preview a context pack's rendered content |
| `pack inject` | Inject a context pack into an existing prompt file |
| `pack init` | Create a new blank context pack |
| `pack search` | Search the registry index for available rule/context packs |
| `pack install` | Download and install a pack from the registry |
| `pack update` | Fetch the remote registry and install/update all packs |
| `pack dirs` | Show registry and user rules directories |
| `ci init` | Scaffold GitHub Actions and pre-commit hooks into a project |
| `ci status` | Check which CI integrations are active |
| `list-targets` | Show all available model profiles |
| `list-templates` | Show all available prompt templates |
| `validate` | Validate YAML config files — profiles, templates, context packs, workflows, prompt tests |
| `validate-profiles` | Validate all profile YAML files against the profile schema |
| `interactive` | Launch the guided menu — generate, lint, scan, diff, test, and more |

---

### `generate`

Generate an optimised prompt from a rough task description.

```bash
promptgenie generate "refactor the auth module to use JWT" \
  --target claude-code \
  --mode exhaustive
```

```bash
promptgenie generate "threat model the payment API" \
  --target claude \
  --template threat-model \
  --context "Django REST API, Stripe integration, PostgreSQL" \
  --out payment-threat-model.md
```

**Options:**

| Flag | Description |
|---|---|
| `--target`, `-t` | Target AI tool. Auto-inferred if omitted. |
| `--template`, `-T` | Template ID (e.g. `threat-model`, `agentic-task`). Auto-inferred if omitted. |
| `--context`, `-c` | Project or task context. |
| `--constraints`, `-x` | Constraints or forbidden actions. |
| `--output-format`, `-f` | Desired output format for the generated prompt. |
| `--mode`, `-m` | `minimal` / `standard` / `exhaustive` |
| `--out`, `-o` | Save prompt to file. |
| `--pack`, `-p` | Context pack ID to inject (e.g. `react-supabase-app`). |
| `--no-lint` | Skip inline lint pass. |
| `--no-scan` | Skip inline security scan. |

**Modes:**

| Mode | Use for |
|---|---|
| `minimal` | Reasoning models, simple tasks, low token budget |
| `standard` | Default — balanced structure and detail |
| `exhaustive` | Agentic tools, complex tasks, security-critical workflows |

---

### `lint`

Check a prompt file for quality and structural issues.

```bash
# Default rich terminal output
promptgenie lint my-prompt.md

# Machine-readable JSON (CI scripts, dashboards)
promptgenie lint my-prompt.md --format json

# SARIF for GitHub code scanning
promptgenie lint my-prompt.md --format sarif --out lint-results.sarif
```

**What it checks:**

- Vague verbs (`help`, `fix`, `improve`, `make better`)
- Multiple tasks chained in one prompt
- Missing target AI tool
- Overly broad scope (`fix the whole app`, `update all files`)
- Missing stop conditions (agentic prompts)
- Missing scope definition
- Missing forbidden actions
- Missing output format
- Missing success criteria
- Dangerous agentic instructions (`do whatever it takes`, `deploy to production`, `drop the table`)

Exits `1` if any HIGH severity issues are found — safe to use in CI.

**Options:**

| Flag | Description |
|---|---|
| `--format` | Output format: `rich` (default) / `json` / `sarif` |
| `--out`, `-o` | Write output to file instead of stdout |

---

### `scan`

Scan a prompt file for security risks.

```bash
# Default rich terminal output
promptgenie scan my-prompt.md

# Machine-readable JSON
promptgenie scan my-prompt.md --format json

# SARIF for GitHub code scanning upload
promptgenie scan my-prompt.md --format sarif --out scan-results.sarif
```

**What it flags (heuristic patterns):**

| Category | Pattern examples flagged |
|---|---|
| Secrets | API keys, tokens, AWS credentials, private keys embedded in prompt |
| Prompt injection | Instruction overrides, system prompt extraction, output suppression |
| Agent permissions | Unrestricted filesystem access, arbitrary code execution, unsupervised publishing |
| RAG risks | Instructions that follow retrieved content, untrusted input pipelines |
| Chained risks | Web fetch + action (email/deploy/write) without approval gate |

> **Confidence and severity:** findings use `HIGH`/`CRITICAL` labels to reflect the *severity of the pattern class*, not the certainty of detection. Each finding is a heuristic signal — review before treating as a confirmed vulnerability. The scanner uses static regex with NFKC Unicode normalisation and does not detect synonym substitution, indirect reference, or multi-turn attacks. See `tests/test_scanner_adversarial.py` for documented detection gaps.

Exits `1` on CRITICAL or HIGH findings — safe to use in CI or pre-commit hooks.

The scanner reports the **class** of secret found, never the secret value itself.

**Options:**

| Flag | Description |
|---|---|
| `--format` | Output format: `rich` (default) / `json` / `sarif` |
| `--out`, `-o` | Write output to file instead of stdout |

**Scan JSON output** includes `category` (rule category: `secret`, `injection`, `permission`, `rag`, `obfuscation`) and `source` (`builtin` / `registry` / `custom`) on every finding.

**Secret rule IDs** — each secret pattern has a unique code for precise suppression:

| Code | Pattern |
|---|---|
| `SEC_SECRET_APIKEY` | Generic `sk-` / `api_key` patterns |
| `SEC_SECRET_TOKEN` | Generic bearer tokens |
| `SEC_SECRET_OPENAI` | OpenAI `sk-` keys |
| `SEC_SECRET_GOOGLE` | Google API keys (`AIza…`) |
| `SEC_SECRET_SLACK` | Slack tokens (`xox[bpoas]-…`) |
| `SEC_SECRET_PRIVKEY` | PEM private key headers |
| `SEC_SECRET_GITHUB` | GitHub PATs (`ghp_…`, `github_pat_…`) |
| `SEC_SECRET_AWS_KEY` | AWS access key IDs (`AKIA…`) |
| `SEC_SECRET_AWS_SECRET` | AWS secret access key patterns |

Use `SEC_SECRET` as an alias in `enabled_rules` / `disabled_rules` config to target all secret rules at once.

---

### `policy`

CI policy gate — run lint and scan together and exit non-zero if findings exceed configurable thresholds. Designed to be dropped into any GitHub Actions step or pre-push hook.

```bash
# Fail if any HIGH-or-above security finding exists (default)
promptgenie policy my-prompt.md

# Fail if any CRITICAL finding exists, AND lint score drops below 70
promptgenie policy my-prompt.md --max-risk CRITICAL --min-score 70

# Allow up to 2 MEDIUM findings before failing
promptgenie policy my-prompt.md --max-risk MEDIUM --max-findings 2

# Machine-readable JSON output for CI dashboards
promptgenie policy my-prompt.md --format json
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | All thresholds passed — prompt is clean |
| `1` | One or more thresholds exceeded — findings printed |
| `2` | Usage / configuration error (bad file path, invalid config) |

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--max-risk` | `HIGH` | Fail if any security finding is at or above this level (`CRITICAL` / `HIGH` / `MEDIUM` / `LOW`) |
| `--max-findings` | `0` | Fail if total qualifying findings exceed this count; `0` = any qualifying finding fails |
| `--min-score` | `0` | Fail if lint quality score is below this value; `0` = lint score not checked |
| `--format` | `text` | Output format: `text` (Rich table), `json` (machine-readable), or `sarif` (SARIF v2.1.0) |
| `--config PATH` | — | Path to `.promptgenie.yaml` |
| `--no-config` | — | Ignore any `.promptgenie.yaml` |

**Expired allowlist warnings** — when the loaded config contains allowlist entries that have expired (or have a malformed `expires` date), the policy command surfaces them:
- `--format json`: `allowlist_warnings` array in the output document
- `--format text`: `⚠ Allowlist: …` line per expired entry in the Rich output

This keeps stale suppressions visible in CI rather than silently inactive.

**Example GitHub Actions steps:**

```yaml
# Text output with Rich table — good for human-readable CI logs
- name: PromptGenie policy gate
  run: promptgenie policy my-prompt.md --max-risk HIGH --min-score 75

# SARIF output — upload to GitHub Code Scanning
- name: PromptGenie policy (SARIF)
  run: promptgenie policy my-prompt.md --format sarif --max-risk MEDIUM > policy.sarif

- name: Upload SARIF results
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: policy.sarif
```

---

### `diff`

Compare two prompt versions side-by-side — tokens, quality scores, section changes, lint changes, and security finding changes.

```bash
promptgenie diff v1.md v2.md --target claude-code
promptgenie diff v1.md v2.md --target claude-code --unified
```

**What it shows:**

| Panel | Content |
|---|---|
| **Summary** | Tokens, quality score, lint count, security findings — A vs B with delta |
| **Quality Score Breakdown** | All 7 dimensions side-by-side with per-dimension delta |
| **Section Changes** | Each `## Section` marked ADDED / REMOVED / CHANGED / UNCHANGED with inline line diffs |
| **Lint Changes** | Issues resolved in v2 vs new issues introduced |
| **Security Changes** | Findings resolved in v2 vs new findings introduced |

**Options:**

| Flag | Description |
|---|---|
| `--target`, `-t` | Profile to use for quality scoring (default: `claude`) |
| `--unified`, `-u` | Show full colour-coded unified diff |

---

### `adapt`

Translate a prompt written for one target into another — rewriting model-specific language, preserving agentic safety sections by default, and adding sections required by the destination profile.

```bash
# Claude Code → Cursor (same agentic category — all safety sections kept)
promptgenie adapt my-prompt.md --from claude-code --to cursor

# Claude Code → ChatGPT (safety sections preserved by default)
promptgenie adapt my-prompt.md --from claude-code --to chatgpt --out chatgpt-prompt.md

# Explicitly strip safety sections when adapting to a non-agentic target
promptgenie adapt my-prompt.md --from claude-code --to chatgpt --strip-agentic-safety

# Show original alongside adapted version
promptgenie adapt my-prompt.md --from claude-code --to gemini --show-original
```

**What it does:**

| Scenario | Behaviour |
|---|---|
| Agentic → Agentic (e.g. `claude-code` → `cursor`) | Keeps all sections, rewrites model name |
| Agentic → General, default (e.g. `claude-code` → `chatgpt`) | **Preserves** scope / stop conditions / constraints; notes in change log |
| Agentic → General with `--strip-agentic-safety` | Drops scope / stop conditions / constraints, warns you, trims tokens |
| Missing required sections | Generates default content from the destination profile |
| Forbidden patterns in content | Replaces with `[REMOVED — forbidden by target profile]` |

> **Safety-first default:** agentic safety sections (stop conditions, forbidden actions, scope, constraints, verification) are kept when adapting to a non-agentic target. Use `--strip-agentic-safety` to opt in to stripping them — useful when you need a minimal token footprint and have verified the target context is safe.

Outputs a colour-coded change log (KEPT / REWRITTEN / ADDED / DROPPED per section) and a score and token summary with delta.

**Options:**

| Flag | Description |
|---|---|
| `--from` | Source target profile |
| `--to` | Destination target profile |
| `--out`, `-o` | Save adapted prompt to file |
| `--show-original` | Print original alongside adapted version |
| `--strip-agentic-safety` | Remove agentic safety sections when adapting to a non-agentic target (off by default) |

---

### `test`

Run a declarative prompt test suite defined in a `.prompt-test.yaml` file. Assert content, structure, quality scores, token budgets, lint severity, and security risk — all without sending the prompt to a model.

```bash
promptgenie test my-suite.prompt-test.yaml
promptgenie test my-suite.prompt-test.yaml --verbose
```

**Test file format:**

```yaml
prompt: path/to/my-prompt.md   # relative to the test file
target: claude-code
description: "Auth refactor prompt — safety and quality assertions"

tests:
  - name: has explicit stop conditions
    must_include:
      - "Stop and ask"
      - "approval"

  - name: scope is restricted
    must_include:
      - "src/auth"
    must_not_include:
      - "entire codebase"
      - "fix everything"

  - name: no unsafe agentic patterns
    must_not_include:
      - "do whatever it takes"
      - "deploy to production"

  - name: required sections present
    required_sections:
      - Objective
      - Scope
      - Stop Conditions
      - Acceptance Criteria

  - name: quality score threshold
    min_score: 80

  - name: token budget
    max_tokens: 500

  - name: no high lint issues
    max_lint_severity: MEDIUM

  - name: no high security findings
    max_security_risk: MEDIUM

  - name: no production deployment pattern
    regex_not_match:
      - "deploy to (prod|production|live)"
```

**All assertion types:**

| Assertion | What it checks |
|---|---|
| `must_include` | Phrase is present in the prompt (case-insensitive) |
| `must_not_include` | Phrase is absent from the prompt |
| `required_sections` | `## Section` heading exists |
| `regex_match` | Regex matches anywhere in the prompt |
| `regex_not_match` | Regex does not match |
| `min_score` | Quality score ≥ threshold |
| `max_tokens` | Token count ≤ budget |
| `max_lint_severity` | No lint issue worse than HIGH / MEDIUM / LOW |
| `max_security_risk` | No security finding worse than CRITICAL / HIGH / MEDIUM / LOW |

Exits `0` on full pass, `1` on any failure — safe to run in CI or as a pre-commit hook.

**Options:**

| Flag | Description |
|---|---|
| `--verbose`, `-v` | Show all assertions including passing ones |

See [`examples/auth-refactor.prompt-test.yaml`](examples/auth-refactor.prompt-test.yaml) for a full working example.

---

### `benchmark`

Run a prompt against a Claude model, score the response across 6 rubric dimensions using a judge model, and report token usage, latency, and estimated cost. Compare two prompts head-to-head across multiple runs.

```bash
# Requires ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-...

# Single run
promptgenie benchmark my-prompt.md

# Specific model, print full response
promptgenie benchmark my-prompt.md --model claude-opus-4-8 --show-response

# Average scores across 3 runs
promptgenie benchmark my-prompt.md --runs 3

# Compare two prompt versions head-to-head
promptgenie benchmark v1.md --compare v2.md --runs 3

# Save model response to file
promptgenie benchmark my-prompt.md --out response.md
```

**Rubric dimensions:**

| Dimension | What it measures |
|---|---|
| Relevance | Did the response address the prompt objective? |
| Completeness | Were all tasks, sections, and requirements covered? |
| Format Compliance | Did the output match the requested format? |
| Safety Compliance | Did the response respect constraints and stop conditions? |
| Conciseness | Was the output free of padding and unnecessary repetition? |
| Actionability | Is the output specific, concrete, and immediately usable? |

**What it outputs:**

| Panel | Content |
|---|---|
| **Benchmark** | Score per dimension + overall, model, latency, token usage (with cache breakdown), estimated cost |
| **Judge Reasoning** | One-sentence explanation per dimension from the judge model |
| **Prompt Comparison** | Side-by-side A vs B scores with delta column, when `--compare` is used |

The response is scored by a separate judge call (claude-haiku — fast and cheap) so benchmark results are comparable across models and prompt versions. Prompt caching is applied to the judge system prompt, reducing cost on repeated runs.

**Options:**

| Flag | Description |
|---|---|
| `--model`, `-m` | Claude model to benchmark (default: `claude-sonnet-4-6`) |
| `--runs`, `-n` | Number of runs — scores are averaged (default: 1) |
| `--compare`, `-c` | Second prompt file to benchmark and compare |
| `--api-key` | Anthropic API key (or set `ANTHROPIC_API_KEY`) |
| `--show-response` | Print full model response to terminal |
| `--out`, `-o` | Save model response to file |
| `--yes`, `-y` | Skip external-send confirmation prompt (for CI/non-interactive use) |

**Provider abstraction:**

`benchmark` is backed by a `ModelProvider` protocol. The default is `AnthropicProvider`. To plug in a different backend, implement the three-method interface and pass it to `run_benchmark()` in Python:

```python
from promptgenie.core.benchmarker import run_benchmark, ModelProvider

class MyProvider:
    def complete(self, model, prompt, system=None):
        # returns (response_text, {"input": n, "output": n, "cache_read": 0, "cache_write": 0})
        ...
    def judge_model(self):
        return "my-judge-model"
    def estimate_cost(self, model, input_tokens, output_tokens, cache_read, cache_write):
        return 0.0

results = run_benchmark("my-prompt.md", model="my-model", provider=MyProvider())
```

---

### `workflow`

Break a complex task into a staged prompt chain — one focused prompt per step, with handoffs, approval gates, per-step scope locks, and stop conditions. Agentic tools perform significantly better with staged prompts than with a single large prompt.

```bash
# Show all steps + full prompts
promptgenie workflow my-feature.workflow.yaml

# Summary and step index only
promptgenie workflow my-feature.workflow.yaml --summary

# Show a single step
promptgenie workflow my-feature.workflow.yaml --step 3

# Save all steps as individual .md files
promptgenie workflow my-feature.workflow.yaml --out ./prompts/
```

**`.workflow.yaml` format:**

```yaml
name: secure-login-feature
description: "Build a secure JWT login system end-to-end"
target: claude-code
context_pack: react-supabase-app   # optional — injected into step 1
mode: standard

steps:
  - id: inspect
    name: Inspect existing auth
    objective: "Map the current authentication architecture and identify gaps"
    scope:
      - src/auth/
      - src/middleware/
    output: "Architecture summary with file map and identified gaps"

  - id: plan
    name: Propose implementation plan
    depends_on: inspect
    objective: "Propose a JWT implementation plan based on the inspection"
    output: "Numbered plan with file list and risk notes"
    requires_approval: true        # model stops here for human review

  - id: implement
    name: Implement middleware
    depends_on: plan
    objective: "Implement JWT middleware only, as per the approved plan"
    scope:
      - src/middleware/auth.ts
    forbidden:
      - Do not touch files outside scope
      - Do not install packages without approval
    stop_conditions:
      - Tests fail
      - A file outside scope needs changing
    output: "Diff of changed files + test results"

  - id: security-review
    name: Security review
    depends_on: implement
    objective: "Security review of the JWT implementation"
    output: "Findings table: | Finding | Severity | Recommendation |"
    requires_approval: true
```

**Step fields:**

| Field | Description |
|---|---|
| `id` | Unique step identifier (used in `depends_on`) |
| `name` | Human-readable step name |
| `objective` | What this step must accomplish |
| `depends_on` | ID of the step that must complete first |
| `scope` | Files or directories the model may touch |
| `forbidden` | Actions explicitly prohibited in this step |
| `stop_conditions` | Conditions that require stopping and asking for approval |
| `output` | Expected output format or deliverable |
| `requires_approval` | If `true`, inserts an approval gate — model will not proceed |
| `context_note` | Optional extra notes for this step |

**What each rendered step contains:**

- Workflow header and step number
- Handoff summary from the previous step
- Objective, scope, forbidden actions, stop conditions
- Approval gate notice (if set)
- Expected output and acceptance criteria

**Options:**

| Flag | Description |
|---|---|
| `--summary` | Show step index only — no prompt content |
| `--step N` | Render a single step by number |
| `--out DIR` | Save all steps as `step_01_name.md` files in a directory |

See [`examples/secure-login.workflow.yaml`](examples/secure-login.workflow.yaml) for a full 6-step example with approval gates and a context pack.

---

### `pack`

Context packs are reusable YAML files that capture everything a model needs to know about your project — stack, architecture, coding style, forbidden changes, known pitfalls, and terminology. Use them to stop repeating yourself across every prompt.

PromptGenie also ships a **plugin registry** — a versioned index of rule packs and context packs that can be installed with `pack update` or `pack install`. Registry packs are stored in `~/.promptgenie/registry/packs/` and loaded automatically by the scanner and linter when referenced via `rules_dirs` config.

**Search the registry:**

```bash
promptgenie pack search
promptgenie pack search owasp
```

**Install a specific pack:**

```bash
promptgenie pack install owasp-llm-top10
```

Both `pack install` and `pack update` verify the SHA-256 checksum of every downloaded file against the registry index. Install is refused if no checksum is present. Pass `--allow-unverified` only when using a private registry that does not yet publish checksums (a visible warning is shown):

```bash
# Private registry without checksums — bypass with explicit opt-in
promptgenie pack install my-private-pack --allow-unverified
promptgenie pack update --url https://my-registry.example.com/index.yaml --allow-unverified
```

**Update all packs from the remote registry:**

```bash
promptgenie pack update
```

**Show registry and user directories:**

```bash
promptgenie pack dirs
```

**Built-in packs (shipped with PromptGenie, no network required — 14 total):**

| Pack ID | Type | Description |
|---|---|---|
| `owasp-llm-top10` | rules | OWASP LLM Top 10 scanner rules (2025 edition) |
| `enterprise-lint` | rules | Enterprise prompt governance lint rules |
| `gpt-4o` | profile | OpenAI GPT-4o — multimodal, function-calling, structured output |
| `mistral` | profile | Mistral AI — instruction-following and multilingual tasks |
| `llama3` | profile | Meta Llama 3 — open-source / self-hosted / fine-tuning |
| `github-copilot` | profile | GitHub Copilot — IDE-embedded code generation |
| `devops-templates` | template | DevOps & SRE — runbooks, postmortems, CI/CD, on-call handoffs |
| `data-science-templates` | template | Data Science & ML — EDA, model eval, experiment design, model cards |
| `legal-compliance-templates` | template | Legal & Compliance — contracts, GDPR DPIA, regulatory gap analysis |
| `product-management-templates` | template | Product Management — PRD, user stories, OKRs, retros |
| `customer-support-templates` | template | Customer Support & Success — triage, escalation, KB articles |
| `ai-safety-context` | context | AI safety context pack for alignment-aware prompting |
| `responsible-ai-context` | context | Responsible AI — fairness, explainability, harm prevention |
| `regulated-industries-context` | context | Regulated industries — HIPAA, SOX, PCI-DSS, FCA/SEC |

**Enable registry packs via config:**

```yaml
# .promptgenie.yaml
scanner:
  rules_dirs:
    - ~/.promptgenie/registry/packs   # registry installs
    - ./local-rules                   # project-local rules
  enabled_rules:                      # whitelist — only run these codes
    - OWASP_LLM01_001
    - OWASP_LLM02_001
    - SEC_SECRET                      # alias — expands to all SEC_SECRET_* sub-rules

linter:
  rules_dirs:
    - ~/.promptgenie/registry/packs
  enabled_rules:
    - ENT_001
    - ENT_003
```

**Expiring allowlist entries** — time-limit exceptions with automatic re-activation after the expiry date:

```yaml
scanner:
  allowlist:
    - phrase: "sk-ant-ci-placeholder"
      rules:
        - SEC_SECRET
      expires: "2026-12-31"
      reason: "CI placeholder — rotate before expiry, see ticket #456"
```

**List available packs:**

```bash
promptgenie pack list
```

**Preview a pack's rendered content:**

```bash
promptgenie pack show react-supabase-app
promptgenie pack show react-supabase-app --mode exhaustive
```

**Generate a prompt with a pack injected:**

```bash
promptgenie generate "refactor the auth module" \
  --target claude-code \
  --pack react-supabase-app \
  --mode exhaustive
```

The pack is rendered at the same depth as the prompt mode and injected into the Context section automatically.

**Inject a pack into an existing prompt file:**

```bash
promptgenie pack inject my-prompt.md react-supabase-app
promptgenie pack inject my-prompt.md react-supabase-app --out enriched-prompt.md
```

**Create your own pack:**

```bash
promptgenie pack init my-project --name "My App" --description "Next.js + Prisma SaaS"
# Edit the generated file at promptgenie/context-packs/my-project.yaml
```

**Pack file format:**

```yaml
name: react-supabase-app
description: "React + Supabase SaaS application"

stack:
  - React 18 + TypeScript
  - Supabase (auth, database, storage)
  - Tailwind CSS + shadcn/ui

architecture:
  - SPA with React Router v6
  - Supabase RLS for all data access

coding_style:
  - Functional components only
  - Custom hooks for all data fetching

forbidden_changes:
  - Do not modify Supabase migration files directly
  - Do not disable Row-Level Security on any table

known_pitfalls:
  - RLS policies must be updated when adding new tables
  - Edge functions have a cold start — avoid for latency-sensitive paths

terminology:
  workspace: "Top-level organisational unit"
  member: "A user who belongs to a workspace"

preferred_output_format: "TypeScript with explicit return types"
```

**Render modes:**

| Mode | Sections included |
|---|---|
| `minimal` | Stack only |
| `standard` | Stack, architecture, coding style, terminology |
| `exhaustive` | All sections including forbidden changes and known pitfalls |

**Included starter packs:**

| ID | Stack |
|---|---|
| `react-supabase-app` | React 18 + TypeScript + Supabase + Tailwind CSS |
| `django-rest-api` | Django 5 + DRF + PostgreSQL + Celery |
| `cyber-security-team` | Python + Splunk + Sigma + AWS + Burp Suite |

Packs are stored in `promptgenie/context-packs/*.yaml` and can be committed alongside your code.

---

### `ci`

Add prompt quality gates to any project in one command. Scaffolds a GitHub Actions workflow and pre-commit hooks that automatically run lint, scan, and test on prompt files.

**Set up CI in any project:**

```bash
cd my-project
promptgenie ci init
```

Creates three files if they don't already exist:

| File | Purpose |
|---|---|
| `.github/workflows/prompt-check.yml` | GitHub Actions — 3 parallel jobs: lint, scan, test |
| `.pre-commit-config.yaml` | Pre-commit hooks for staged `.prompt.md` and test files |
| `.promptignore` | Glob patterns to exclude from lint/scan checks |

The main `ci.yml` runs 5 parallel jobs: `test` (Python 3.10–3.12, coverage ≥85%), `lint` (ruff, mypy), `security` (bandit, pip-audit), `vscode-extension` (npm ci, audit, compile, lint), and `build` (wheel smoke test).

**Check what's active:**

```bash
promptgenie ci status
```

```
╭──────────────────────────────────────────────┬──────────╮
│ Integration                                  │  Status  │
├──────────────────────────────────────────────┼──────────┤
│ GitHub Actions (prompt-check.yml)            │ ✓ Active │
│ Pre-commit hooks (.pre-commit-config.yaml)   │ ✓ Active │
│ .promptignore exclusion file                 │ ✓ Active │
│ Git repository                               │ ✓ Active │
╰──────────────────────────────────────────────┴──────────╯
```

**GitHub Actions behaviour:**

The workflow triggers on any push or pull request touching `.md`, `.prompt-test.yaml`, or `.workflow.yaml` files and runs three parallel jobs:

| Job | Command | Fails on |
|---|---|---|
| `prompt-lint` | `promptgenie lint` per file | Any HIGH severity issue |
| `prompt-scan` | `promptgenie scan` per file | Any HIGH or CRITICAL finding |
| `prompt-test` | `promptgenie test` per suite | Any assertion failure |

**Pre-commit hooks:**

```bash
pip install pre-commit && pre-commit install
# Hooks run automatically on every git commit
```

Hooks check staged `.prompt.md` files with lint and scan, and staged `.prompt-test.yaml` files with test — before the commit lands.

**`.promptignore`:**

```
# Exclude these paths from lint/scan
README.md
CHANGELOG.md
docs/**
```

**Options:**

| Flag | Description |
|---|---|
| `--dir` | Target directory (default: current directory) |

---

### `list-targets`

Show all available model profiles.

```bash
promptgenie list-targets
```

---

### `list-templates`

Show all available prompt templates.

```bash
promptgenie list-templates
```

---

### `validate`

Validate YAML config files against their schema. Accepts file paths and auto-detects type (profile, template, context pack, workflow, prompt-test). Use `--all` to validate all built-in files.

```bash
# Validate a single file
promptgenie validate my-profile.yaml

# Validate a workflow
promptgenie validate examples/secure-login.workflow.yaml

# Validate all built-in profiles, templates, and context packs
promptgenie validate --all
```

Errors exit 1 (blocking). Warnings exit 0 (advisory — missing recommended fields, unknown keys).

---

### `validate-profiles`

Validate all profile YAML files against the profile schema. Checks required fields, category values, list types, slug format, and unknown keys.

```bash
# Validate built-in profiles
promptgenie validate-profiles

# Validate profiles in a custom directory
promptgenie validate-profiles --dir ./my-profiles

# Suppress advisory warnings (errors still shown)
promptgenie validate-profiles --no-warnings
```

---

## Target Profiles

| ID | Name | Category |
|---|---|---|
| `claude` | Claude | General assistant |
| `claude-code` | Claude Code | Agentic coding |
| `chatgpt` | ChatGPT | General assistant |
| `cursor` | Cursor | IDE coding |
| `gemini` | Gemini | General assistant / multimodal |

Each profile defines required sections, forbidden patterns, stop conditions, security controls, and a default output format. Stored in `promptgenie/profiles/*.yaml`.

---

## Templates

| ID | Name | Category |
|---|---|---|
| `agentic-task` | Agentic Task Brief | Coding |
| `threat-model` | Threat Model | Security |
| `secure-code-review` | Secure Code Review | Security |
| `soc-triage` | SOC Alert Triage | Security operations |
| `pentest` | Penetration Test Plan | Security |
| `iac-review` | IaC Security Review | Security |
| `prompt-injection-test` | Prompt Injection Test Suite | Security |

Stored in `promptgenie/templates/*.yaml`.

---

## Quality Score

Every generated prompt is scored across 7 dimensions:

| Dimension | What it measures |
|---|---|
| Target Fit | Required sections present for the target tool |
| Task Clarity | Absence of vague verbs and ambiguous framing |
| Context Sufficiency | Enough context for the model to act without guessing |
| Output Contract | Output format explicitly defined |
| Safety Controls | Stop conditions, forbidden actions, constraints present |
| Token Efficiency | Prompt length relative to complexity |
| Testability | Acceptance criteria or success definition present |

Score of 80+ is considered production-ready. Below 60 triggers lint warnings automatically.

> **Score note:** quality scores are local heuristic estimates based on structural markers (sections present, vague words, length, output format signals). They are not an objective measurement of prompt effectiveness — treat them as a relative hygiene signal, not a grade.

---

## Project structure

```
promptgenie/
├── cli.py                      # Click group + command registration
├── commands/
│   ├── generate.py             # generate command
│   ├── lint.py                 # lint command
│   ├── scan.py                 # scan command
│   ├── diff.py                 # diff command
│   ├── adapt.py                # adapt command
│   ├── test.py                 # test command
│   ├── benchmark.py            # benchmark command
│   ├── workflow.py             # workflow command
│   ├── ci.py                   # ci group (init, status)
│   ├── pack.py                 # pack group (list, show, inject, init, search, install, update, dirs)
│   ├── policy.py               # policy command — CI gate (exit 0/1/2)
│   ├── targets.py              # list-targets, list-templates
│   └── interactive.py          # guided interactive menu mode
├── renderers/
│   └── rich.py                 # console, color constants, shared formatting helpers
├── core/
│   ├── generator.py            # Prompt builder, scoring, token estimation
│   ├── linter.py               # Lint rules engine
│   ├── scanner.py              # Security scanner
│   ├── differ.py               # Diff engine — token, score, section, risk delta
│   ├── adapter.py              # Adapt engine — cross-profile prompt translation
│   ├── tester.py               # Test runner — declarative prompt unit tests
│   ├── benchmarker.py          # Benchmark engine — model calls, rubric scoring, cost
│   ├── context_packs.py        # Context pack engine — load, render, inject, init
│   ├── workflow.py             # Workflow engine — staged prompt chains
│   ├── ci.py                   # CI scaffolder — GitHub Actions + pre-commit
│   ├── config.py               # .promptgenie.yaml config loader
│   ├── registry.py             # Pack registry — remote index, install, update, rule loading
│   └── formatters.py           # Structured output — JSON and SARIF v2.1.0
├── registry/
│   ├── index.yaml              # Built-in registry index (14 packs)
│   └── packs/
│       ├── owasp-llm-top10.yaml            # OWASP LLM Top 10 scanner rules
│       ├── enterprise-lint.yaml            # Enterprise governance lint rules
│       ├── gpt-4o.yaml                     # OpenAI GPT-4o profile
│       ├── mistral.yaml                    # Mistral AI profile
│       ├── llama3.yaml                     # Meta Llama 3 profile
│       ├── github-copilot.yaml             # GitHub Copilot profile
│       ├── devops-templates.yaml           # DevOps & SRE templates
│       ├── data-science-templates.yaml     # Data Science & ML templates
│       ├── legal-compliance-templates.yaml # Legal & Compliance templates
│       ├── product-management-templates.yaml # Product Management templates
│       ├── customer-support-templates.yaml # Customer Support templates
│       ├── ai-safety-context.yaml          # AI safety context pack
│       ├── responsible-ai-context.yaml     # Responsible AI context pack
│       └── regulated-industries-context.yaml # Regulated industries context
├── profiles/
│   ├── claude.yaml
│   ├── claude-code.yaml
│   ├── chatgpt.yaml
│   ├── cursor.yaml
│   └── gemini.yaml
├── templates/
│   └── cyber_templates.yaml    # 7 security and coding templates
├── context-packs/
│   ├── react-supabase-app.yaml             # React + Supabase SaaS
│   ├── django-rest-api.yaml                # Django + DRF + PostgreSQL
│   └── cyber-security-team.yaml           # Security engineering team
├── examples/
│   ├── auth-refactor.md                    # Example prompt
│   ├── auth-refactor.prompt-test.yaml      # Example test suite
│   └── secure-login.workflow.yaml          # Example 6-step workflow
├── .github/
│   └── workflows/
│       └── prompt-check.yml                # GitHub Actions — lint, scan, test
├── .github/
│   ├── CODEOWNERS                          # Code ownership (all files → @mylesagnew)
│   └── workflows/
│       ├── ci.yml                          # Pytest (3.10–3.12), ruff, mypy, bandit, pip-audit, build
│       ├── prompt-check.yml                # Lint, scan, and test prompt files on every PR
│       └── release.yml                     # Tag-triggered PyPI publish + SBOM + GitHub Release
├── .pre-commit-config.yaml                 # Pre-commit hooks
├── .promptgenie.yaml.example               # Example project config (rules, suppressions, overrides)
├── SECURITY.md                             # Vulnerability reporting and scanner limitations
├── CONTRIBUTING.md                         # Contributor guide, rule authoring, profile/template schema
├── CHANGELOG.md                            # Version history
├── vscode-extension/                       # VS Code / Cursor extension
│   ├── package.json                        # Extension manifest (commands, settings, activation events)
│   ├── package-lock.json                   # Locked npm dependencies (required for npm ci in CI)
│   ├── tsconfig.json
│   ├── src/
│   │   ├── extension.ts                    # Activate / deactivate, event wiring
│   │   ├── runner.ts                       # CLI subprocess wrapper (lint/scan → JSON)
│   │   ├── diagnostics.ts                  # LintOutput / ScanOutput → VS Code Diagnostics
│   │   ├── statusBar.ts                    # Score + issue count in the status bar
│   │   └── types.ts                        # TypeScript interfaces for CLI JSON output
│   └── README.md                           # Extension-specific docs
└── pyproject.toml                          # Modern packaging, coverage gate, dev dependency groups
```

---

## Roadmap

### Shipped

- [x] `generate` — build structured prompts from rough task descriptions
- [x] `lint` — 15+ rules for quality, scope, and agentic safety
- [x] `scan` — security scanner for secrets, injection, and agent risks
- [x] `diff` — compare two prompt versions with token, score, section, and risk delta
- [x] `adapt` — translate a prompt from one target profile to another
- [x] `test` — declarative prompt unit tests with 8 assertion types, CI-safe
- [x] `benchmark` — run prompt against Claude, score with judge model, compare versions
- [x] Context packs — reusable project context blocks with stack, architecture, style, pitfalls
- [x] Workflow mode — staged prompt chains with approval gates, handoffs, and per-step scope locks
- [x] GitHub Actions + pre-commit CI integration — lint, scan, and test in every PR
- [x] CONTRIBUTING.md — contributor guide, rule authoring docs, profile/template schema reference
- [x] CHANGELOG.md — full version history in Keep a Changelog / Semver format
- [x] `interactive` — guided menu mode: generate, adapt, lint, scan, diff, test, workflow, list in one flow
- [x] `.promptgenie.yaml` config — project-level rule suppressions, severity overrides, allowlists (scoped `AllowlistEntry` format), custom vague verbs; wired into all five CLI commands with `--config` / `--no-config` flags
- [x] Coverage gate — `fail_under = 85` enforced in CI; 567 tests, 0 ruff issues, 0 mypy errors, 0 high-severity bandit issues across `promptgenie/` and `tests/`
- [x] CODEOWNERS — `.github/CODEOWNERS` governs all files; branch protection docs in CONTRIBUTING.md
- [x] Adversarial scanner tests — `TestDetects` (21 caught patterns incl. Unicode normalization, split-line overrides, base64 blobs, HTML/block-comment smuggling), `TestMisses` (7 documented gaps: within-word splits, non-NFKC homoglyphs, word-spacing, synonyms, indirect reference, role-shift, markdown bold), `TestScopedAllowlist` (regression suite for fixed allowlist logic)
- [x] Scoped scanner allowlist — `AllowlistEntry` replaces broken whole-prompt suppression; phrase matched against finding's `matched_text` only; rule-scoped entries filter by code first
- [x] Scanner hardening — NFKC Unicode normalization, split/multiline override patterns (`SEC_SPLIT_001–004`), base64 payload detection (`SEC_B64`), scanner limitations footer in rich output

---

### P0 — Must do before serious adoption

- [x] **Automated test suite** — 306 tests: scanner, linter, generator, differ, adapter, tester, CLI smoke tests, formatter output — 0 warnings
- [x] **Developer CI pipeline** — `ci.yml`: pytest (3.10–3.12) with coverage gate, ruff, mypy, bandit, pip-audit, build + wheel smoke test
- [x] **Modern packaging** — `pyproject.toml` with dev dependency groups, classifiers, project URLs; setuptools license field modernised; `anthropic` and `tiktoken` moved to optional extras (`[benchmark]`, `[tokenizer]`) — default install no longer requires an HTTP API client
- [x] **Generated CI supply-chain hygiene** — `ci init` scaffolds SHA-pinned `actions/checkout` + `astral-sh/setup-uv` (matching the repo's own CI); installs pinned `promptgenie==<version>` via `uv pip install --system`; adds `permissions: contents: read`; replaces `for file in $(find …)` with safe `while IFS= read -r` loop
- [x] **SECURITY.md** — vulnerability reporting, scanner limitations, safe secret handling policy
- [x] **Structured output** — `--format json` and `--format sarif` on lint and scan; SARIF uploaded to GitHub code scanning
- [x] **Adapter safety fix** — preserve agentic safety sections by default; add `--strip-agentic-safety` as explicit opt-in
- [x] **Fix CI green** — replaced invalid `pip-audit -q` flag; resolved 61 ruff issues; fixed 13 mypy errors; added mypy to lint job; SHA-pinned all GitHub Actions in all workflows; added least-privilege `permissions: contents: read`
- [x] **Versioning single source of truth** — `__init__.py` and `cli.py` now read version from `importlib.metadata`; `pyproject.toml` aligned to `1.0.2`; version test no longer hard-codes a string

---

### P1 — High-value reliability

- [x] **Schema validation** — thorough field-level validation for profiles (required fields, category allowlist, slug format, type checks, unknown key detection), templates (id slug, sections non-empty), and context packs; `validate-profiles` command with `--dir` and `--no-warnings` flags; errors fail CI, warnings advisory; 39 new tests
- [x] **File IO safety** — `promptgenie/core/fileio.py`: `safe_read_text` (1 MB limit), `safe_read_yaml` (512 KB limit), `safe_write_text` (atomic via tempfile+rename, `--force` required to overwrite); all 38 read/write call sites migrated; explicit UTF-8 everywhere
- [x] **Data-driven rule packs** — scanner and linter rules migrated to typed `ScanRule`/`LintRule` registry with `id`, `category`, `pattern`, `risk/severity`, `confidence`, `message`, `recommendation`, and `false_positive_note`; custom rules loadable from `.promptgenie.yaml` under `scanner.custom_rules` and `linter.custom_rules`
- [x] **Rule suppression and config** — `.promptgenie.yaml` supports `disabled_rules`, `severity_overrides`, `custom_vague_verbs`, and a scoped `allowlist` (`AllowlistEntry` with optional `rules` filter); suppression is matched against the finding's `matched_text`, not the whole prompt; config is now loaded and applied by all five CLI commands (`scan`, `lint`, `generate`, `test`, `diff`) with `--config PATH` and `--no-config` flags
- [x] **CLI refactor** — split `cli.py` into `commands/` modules and `renderers/rich.py`; keep core business logic testable without terminal output
- [x] **Context pack path validation** — strict slug regex `^[A-Za-z0-9_-]+$` on `pack_id`; path containment enforced in `load_pack` and `init_pack`; 10 traversal rejection tests added
- [x] **Workflow schema validation and cycle detection** — `validate_workflow()` checks duplicate IDs, required fields, unknown dependencies, and cycles (DFS with visiting/visited sets); `WorkflowValidationError` surfaced cleanly in CLI; 13 tests covering valid DAGs, cycles, self-references, and bad fields
- [x] **ReDoS protection for prompt-test regex** — `_safe_search()` helper with 500-char length guard and `SIGALRM`-based 5s timeout on POSIX; invalid regex returns error assertion instead of exception; 7 tests including known ReDoS pattern and max-length boundary
- [x] **Benchmark cost controls and judge hardening** — `--runs` bounded via `click.IntRange(max=10)`; API call count printed before execution; judge parse failure sets `judge_parse_failed=True` and emits CLI warning instead of silent score-50; judge system prompt hardened with explicit untrusted-data instruction; `BenchmarkEvaluationError` raised on bad JSON; 12 tests added
- [x] **Dependency lockfile strategy** — `uv.lock` committed (108 packages with hashes); CI now installs via `uv sync --frozen`; Dependabot configured for weekly `uv` and `github-actions` updates; `cyclonedx-bom` added to dev deps
- [x] **Line-level SARIF locations** — `SecurityFinding` and `LintIssue` now carry `line`, `col`, and `confidence` fields; `_offset_to_line_col()` converts regex match offsets to 1-based line/col; SARIF output emits `region.startLine`/`startColumn`; `confidence` surfaced in both SARIF `properties` and JSON output; `TOOL_VERSION` reads from `importlib.metadata`; 17 new tests
- [x] **Least-privilege GitHub token permissions** — shipped in Wave 1 (1.0.3)
- [x] **Improve pre-commit hooks** — `.pre-commit-config.yaml` now uses SHA-pinned upstream repos: `astral-sh/ruff-pre-commit` (ruff + ruff-format), `pre-commit/pre-commit-hooks` (check-yaml, check-toml, end-of-file-fixer, trailing-whitespace, check-merge-conflict, check-added-large-files), `Yelp/detect-secrets`; `.secrets.baseline` committed; PromptGenie local hooks retained
- [x] **Typed result and config models** — `promptgenie/models.py` adds `Profile`, `Template`, `ContextPackMeta`, `GenerateResult`, `ValidationResult` dataclasses with `from_dict()` constructors and `validate()` methods; new `promptgenie validate` command validates profiles, templates, context packs, workflows, and prompt-test suites (exits 1 on errors); 100% model coverage
- [x] **Fail-closed configuration loading** — remove silent fallbacks on missing profile/template/context-pack; explicit `FileNotFoundError` by default on bad `--target`, `--template`, `--config`, or workflow profile/pack; `--best-effort` flag added to `generate`, `scan`, `lint`, `adapt`, and `workflow` for pipelines where partial output is acceptable _(SecDevOps review: MEDIUM — typos produce plausible but degraded output with no warning)_

---

### P2 — Scaling and enterprise readiness

- [x] **VS Code / Cursor extension** — `vscode-extension/` TypeScript extension; inline lint diagnostics while typing (debounced), full lint + scan on save, status bar quality score, high-risk security alerts, command palette integration (`PromptGenie: Lint File`, `Scan File`, `Lint & Scan`); configurable CLI path, target profile, debounce delay, severity mapping; activates on `.md`, `.txt`, `.prompt`, `.promptgenie` files
- [x] **Community profile and template packs** — 14 built-in registry packs: 4 model profiles (`gpt-4o`, `mistral`, `llama3`, `github-copilot`), 5 domain template packs (DevOps/SRE, Data Science/ML, Legal/Compliance, Product Management, Customer Support), 3 context packs (AI Safety, Responsible AI, Regulated Industries), 2 rule packs (OWASP LLM Top 10, Enterprise Lint); all tagged for search; installable and updatable via `promptgenie pack install / update`
- [x] **Secret scanning for the repo** — `detect-secrets` (SHA-pinned, v1.5.0) wired into pre-commit hooks; `.secrets.baseline` committed; runs on every staged commit
- [x] **SBOM and release provenance** — tag-triggered `release.yml` workflow: version consistency check, full test/lint/security gate, `uv build`, CycloneDX SBOM (`sbom.cyclonedx.json`), PyPI Trusted Publishing via GitHub OIDC (no stored token), GitHub artifact attestations (`actions/attest-build-provenance`), GitHub Release with wheel + sdist + SBOM attached; requires protected `release` environment
- [x] **CodeQL analysis** — GitHub Advanced Security CodeQL for Python on every PR and weekly schedule; uploads SARIF to GitHub Security tab _(SecDevOps review: LOW — improves external trust and OpenSSF Scorecard rating)_
- [x] **Dependabot** — `.github/dependabot.yml` configured for weekly automated PRs on `uv` Python dependencies (grouped dev deps) and `github-actions` versions; vulnerability alerting enabled
- [x] **OpenSSF Scorecard** — weekly scheduled Scorecard workflow; SARIF uploaded to GitHub Security tab via `ossf/scorecard-action`; `publish_results: true` for public badge _(SecDevOps review: LOW — baseline for external trust signals)_
- [x] **Plugin/profile registry** — versioned remote rule and context packs; `promptgenie pack update/install/search/dirs`; `~/.promptgenie/registry/packs/` user install dir; `rules_dirs` config for custom rule directories; `enabled_rules` whitelist mode; `disabled_rules` blacklist; severity overrides; expiring allowlist entries (`expires`, `reason`); 14 built-in packs (2 rule, 4 profile, 5 template, 3 context); SHA-256 checksum verification on downloads; stdlib `urllib.request` only — no new deps
- [x] **Container image** — minimal non-root `python:3.12-slim` Dockerfile; dedicated `promptgenie` user (uid 1001); `.dockerignore` keeps image lean; `benchmark` and `tokenizer` extras included
- [x] **Benchmark model abstraction** — `ModelProvider` protocol decouples benchmarker from Anthropic SDK; `AnthropicProvider` is the built-in implementation; pass any `provider=` to `run_benchmark()`; `api_key` still works as before; 12 new protocol tests _(SecDevOps review: MEDIUM — hard-coded Anthropic dependency limits adoption and evaluation auditability)_
- [x] **Registry hardening** — URL scheme allowlist (HTTPS-only, all `file://`/`http://`/`ftp://` schemes blocked); 1 MiB download cap on all remote fetches; `require_checksum=True` mode for strict CI; fail-closed rule-pack loader (malformed `scanner_rules`/`lint_rules` raises `ValueError`, not silently skipped); fail-closed allowlist expiry (malformed date string treated as expired); `# nosec: B310` annotations with rationale on `urlopen` calls
- [x] **Production-shaped scanner findings** — 9 secret rules now carry unique codes (`SEC_SECRET_APIKEY`, `SEC_SECRET_TOKEN`, `SEC_SECRET_OPENAI`, `SEC_SECRET_GOOGLE`, `SEC_SECRET_SLACK`, `SEC_SECRET_PRIVKEY`, `SEC_SECRET_GITHUB`, `SEC_SECRET_AWS_KEY`, `SEC_SECRET_AWS_SECRET`); `SEC_SECRET_CODES` frozenset for backwards-compatible filtering; `SecurityFinding` gains `category` and `source` fields; `ScanResult.risk_level` returns `"NONE"` (not `"LOW"`) when no findings; scanner uses `re.finditer` + `enumerate()` with `MAX_FINDINGS_PER_RULE = 5` cap per rule
- [x] **`policy` command** — CI gate: `promptgenie policy <file> [--max-risk HIGH] [--max-findings 0] [--min-score 0] [--format text|json]`; exits 0 (pass), 1 (violations), 2 (usage error); text output is a Rich findings table; JSON is machine-readable for dashboards and GitHub step summaries
- [x] **Quality gates green** — `ruff format`: 0 files need reformatting; `mypy`: no errors; `bandit`: 0 high-severity issues; 567 tests pass; coverage 85.31%
- [x] **Registry strict mode** — `update_registry()` defaults to `require_checksum=True`; all 14 built-in registry packs carry verified SHA-256 checksums; `pack install/update` CLI exposes `--allow-unverified` escape hatch with visible warning
- [x] **VS Code extension CI** — `vscode-extension` job in `ci.yml`: `npm ci` + `npm audit --audit-level=high` + `npm run compile` + `npm run lint` + artifact upload; `@typescript-eslint/*` upgraded to fix 6 high-severity vulnerabilities; `package-lock.json` committed
- [x] **Policy SARIF output** — `--format sarif` emits combined SARIF v2.1.0 (lint + scan runs) for GitHub Code Scanning upload
- [x] **Expired allowlist reporting** — `policy` surfaces expired/malformed allowlist entries as `allowlist_warnings` in JSON and `⚠ Allowlist:` in text output

---

## Configuration

Place a `.promptgenie.yaml` file in your project root (or any parent directory). The `scan`, `lint`, `generate`, `adapt`, `workflow`, `test`, and `diff` commands auto-discover and load it on every run.

```yaml
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

**Custom scanner rules** can also be added under `scanner.custom_rules`. Each rule requires `id`, `pattern`, `risk`, `confidence`, `message`, and `recommendation`:

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

Copy `.promptgenie.yaml.example` from the repo root as a starting point.

---

## Development

Dependencies are locked in `uv.lock`. Install [uv](https://docs.astral.sh/uv/) then:

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
uv sync --extra dev
```

**Run tests:**
```bash
uv run pytest tests/
```

**Lint and format:**
```bash
uv run ruff check promptgenie/
uv run ruff format promptgenie/
uv run mypy promptgenie
```

**Security checks:**
```bash
uv run bandit -r promptgenie/ -ll
uv run pip-audit --skip-editable --progress-spinner off
```

**Build:**
```bash
uv build
uv run --with twine twine check dist/*
```

**Generate SBOM:**
```bash
uv run cyclonedx-py environment --output-format json --outfile sbom.cyclonedx.json
```

**Releasing** (maintainers only):
1. Update `version` in `pyproject.toml` and add a `[X.Y.Z]` entry to `CHANGELOG.md`.
2. Run `uv lock` to update the lockfile.
3. Commit, push to `main`, then push a semver tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. The `release.yml` workflow runs the full gate, builds, publishes to PyPI via Trusted Publishing, generates GitHub artifact attestations, generates a CycloneDX SBOM, and creates a GitHub Release — all without a stored API token.

> **One-time setup required:** Create a `release` protected environment in GitHub Settings → Environments (add required reviewer). Configure a PyPI Trusted Publisher for this repo pointing at `.github/workflows/release.yml`.

See [SECURITY.md](SECURITY.md) for the vulnerability reporting process and scanner limitations.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor guide, rule authoring docs, and profile/template schema reference.

See [CHANGELOG.md](CHANGELOG.md) for a full version history.

---

## License

MIT
