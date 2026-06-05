<p align="center">
  <img src="assets/logo.png" alt="PromptGenie" width="600" />
</p>

# PromptGenie

**Secure prompt engineering for AI agents and engineering teams.**

PromptGenie is a CLI that turns rough task descriptions into optimised, tool-specific, security-checked prompts — with a built-in linter, security scanner, diff engine, test runner, model benchmarker, quality scoring, and token estimation.

---

## Why

Most prompt engineering is done by hand, rewritten constantly, and never tested. Prompts for agentic tools (Claude Code, Cursor, Devin) are especially risky: a vague scope or missing stop condition can cause scope creep, destructive edits, or unintended deployments.

PromptGenie makes prompts:

- **Structured** — section-by-section output matched to the target tool's requirements
- **Linted** — catches vague verbs, missing scope, broad tasks, and agentic risks before you send
- **Scanned** — detects secrets, prompt injection patterns, and unsafe agent permissions
- **Diffed** — compare two versions with token delta, score delta, section changes, and risk changes
- **Tested** — declarative unit tests assert quality, safety, structure, and content before you ship
- **Benchmarked** — run prompts against real Claude models and score responses across 6 rubric dimensions
- **Scored** — rates every prompt across 7 quality dimensions
- **Repeatable** — YAML model profiles and templates, versioned alongside your code

---

## Install

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

---

## Commands

| Command | Description |
|---|---|
| `generate` | Build an optimised prompt from a rough task description |
| `lint` | Check a prompt file for quality and structural issues |
| `scan` | Scan a prompt file for security risks |
| `diff` | Compare two prompt versions — token, score, section, and risk delta |
| `adapt` | Translate a prompt from one target profile to another |
| `test` | Run a declarative prompt test suite |
| `benchmark` | Run a prompt against a Claude model and score the output |
| `list-targets` | Show all available model profiles |
| `list-templates` | Show all available prompt templates |

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
promptgenie lint my-prompt.md
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

---

### `scan`

Scan a prompt file for security risks.

```bash
promptgenie scan my-prompt.md
```

**What it detects:**

| Category | Examples |
|---|---|
| Secrets | API keys, tokens, AWS credentials, private keys embedded in prompt |
| Prompt injection | Instruction overrides, system prompt extraction, output suppression |
| Agent permissions | Unrestricted filesystem access, arbitrary code execution, unsupervised publishing |
| RAG risks | Instructions that follow retrieved content, untrusted input pipelines |
| Chained risks | Web fetch + action (email/deploy/write) without approval gate |

Exits `1` on CRITICAL or HIGH findings — safe to use in CI or pre-commit hooks.

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

Translate a prompt written for one target into another — rewriting model-specific language, dropping agentic safety sections for non-agentic targets, and adding sections required by the destination profile.

```bash
# Claude Code → Cursor (same agentic category — keeps all safety sections)
promptgenie adapt my-prompt.md --from claude-code --to cursor

# Claude Code → ChatGPT (drops scope/stop conditions/constraints, warns you)
promptgenie adapt my-prompt.md --from claude-code --to chatgpt --out chatgpt-prompt.md

# Show original alongside adapted version
promptgenie adapt my-prompt.md --from claude-code --to gemini --show-original
```

**What it does:**

| Scenario | Behaviour |
|---|---|
| Agentic → Agentic (e.g. `claude-code` → `cursor`) | Keeps all sections, rewrites model name |
| Agentic → General (e.g. `claude-code` → `chatgpt`) | Drops scope / stop conditions / constraints, warns you, trims tokens |
| Missing required sections | Generates default content from the destination profile |
| Forbidden patterns in content | Replaces with `[REMOVED — forbidden by target profile]` |

Outputs a colour-coded change log (KEPT / REWRITTEN / ADDED / DROPPED per section) and a score and token summary with delta.

**Options:**

| Flag | Description |
|---|---|
| `--from` | Source target profile |
| `--to` | Destination target profile |
| `--out`, `-o` | Save adapted prompt to file |
| `--show-original` | Print original alongside adapted version |

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

---

## Project structure

```
promptgenie/
├── cli.py                      # Click CLI — all commands
├── core/
│   ├── generator.py            # Prompt builder, scoring, token estimation
│   ├── linter.py               # Lint rules engine
│   ├── scanner.py              # Security scanner
│   ├── differ.py               # Diff engine — token, score, section, risk delta
│   ├── adapter.py              # Adapt engine — cross-profile prompt translation
│   ├── tester.py               # Test runner — declarative prompt unit tests
│   └── benchmarker.py          # Benchmark engine — model calls, rubric scoring, cost
├── profiles/
│   ├── claude.yaml
│   ├── claude-code.yaml
│   ├── chatgpt.yaml
│   ├── cursor.yaml
│   └── gemini.yaml
├── templates/
│   └── cyber_templates.yaml    # 7 security and coding templates
└── examples/
    ├── auth-refactor.md                    # Example prompt
    └── auth-refactor.prompt-test.yaml      # Example test suite
```

---

## Roadmap

- [x] `generate` — build structured prompts from rough task descriptions
- [x] `lint` — 15+ rules for quality, scope, and agentic safety
- [x] `scan` — security scanner for secrets, injection, and agent risks
- [x] `diff` — compare two prompt versions with token, score, section, and risk delta
- [x] `adapt` — translate a prompt from one target profile to another
- [x] `test` — declarative prompt unit tests with 8 assertion types, CI-safe
- [x] `benchmark` — run prompt against Claude, score with judge model, compare versions
- [ ] Context packs — reusable project context blocks
- [ ] Workflow mode — staged prompt chains for complex agentic tasks
- [ ] VS Code / Cursor extension
- [ ] GitHub Actions lint/scan integration
- [ ] Community profile and template packs

---

## License

MIT
