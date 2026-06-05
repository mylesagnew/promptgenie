"""
ci.py — scaffold GitHub Actions and pre-commit hooks for prompt quality gates.

promptgenie ci init           — sets up .github/workflows/prompt-check.yml
                                and .pre-commit-config.yaml in the current dir
promptgenie ci status         — check what CI integrations are active
"""

from pathlib import Path

WORKFLOW_CONTENT = """\
name: Prompt Check

on:
  push:
    paths:
      - '**.md'
      - '**.prompt-test.yaml'
      - '**.workflow.yaml'
  pull_request:
    paths:
      - '**.md'
      - '**.prompt-test.yaml'
      - '**.workflow.yaml'

jobs:
  prompt-lint:
    name: Lint prompt files
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
      - name: Install PromptGenie
        run: pip install promptgenie --quiet
      - name: Lint prompt files
        run: |
          FAILED=0
          for file in $(find . -not -path './.git/*' -not -path './.venv/*' \\
            \\( -name '*.prompt.md' -o -name '*.md' \\) \\
            | grep -v README | grep -v CHANGELOG | grep -v LICENSE); do
            echo "Linting: $file"
            promptgenie lint "$file" || FAILED=1
          done
          exit $FAILED

  prompt-scan:
    name: Security scan prompt files
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
      - name: Install PromptGenie
        run: pip install promptgenie --quiet
      - name: Scan prompt files
        run: |
          FAILED=0
          for file in $(find . -not -path './.git/*' -not -path './.venv/*' \\
            \\( -name '*.prompt.md' -o -name '*.md' \\) \\
            | grep -v README | grep -v CHANGELOG | grep -v LICENSE); do
            echo "Scanning: $file"
            promptgenie scan "$file" || FAILED=1
          done
          exit $FAILED

  prompt-test:
    name: Run prompt test suites
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
      - name: Install PromptGenie
        run: pip install promptgenie --quiet
      - name: Run test suites
        run: |
          FAILED=0
          for file in $(find . -not -path './.git/*' -name '*.prompt-test.yaml'); do
            echo "Testing: $file"
            promptgenie test "$file" || FAILED=1
          done
          exit $FAILED
"""

PRE_COMMIT_CONTENT = """\
repos:
  - repo: local
    hooks:
      - id: promptgenie-lint
        name: PromptGenie lint
        language: system
        entry: promptgenie lint
        files: \\.prompt\\.md$
        pass_filenames: true

      - id: promptgenie-scan
        name: PromptGenie security scan
        language: system
        entry: promptgenie scan
        files: \\.prompt\\.md$
        pass_filenames: true

      - id: promptgenie-test
        name: PromptGenie prompt tests
        language: system
        entry: promptgenie test
        files: \\.prompt-test\\.yaml$
        pass_filenames: true
"""

PROMPT_IGNORE_CONTENT = """\
# PromptGenie — files excluded from lint/scan
# Add paths that should not be checked (one per line, supports glob patterns)
README.md
CHANGELOG.md
LICENSE
docs/**
"""


def init_ci(target_dir: str = ".") -> dict[str, Path]:
    root = Path(target_dir).resolve()
    created: dict[str, Path] = {}
    skipped: dict[str, Path] = {}

    # GitHub Actions workflow
    gha_dir = root / ".github" / "workflows"
    gha_dir.mkdir(parents=True, exist_ok=True)
    gha_path = gha_dir / "prompt-check.yml"
    if not gha_path.exists():
        gha_path.write_text(WORKFLOW_CONTENT)
        created["github_actions"] = gha_path
    else:
        skipped["github_actions"] = gha_path

    # Pre-commit config
    precommit_path = root / ".pre-commit-config.yaml"
    if not precommit_path.exists():
        precommit_path.write_text(PRE_COMMIT_CONTENT)
        created["pre_commit"] = precommit_path
    else:
        skipped["pre_commit"] = precommit_path

    # .promptignore
    ignore_path = root / ".promptignore"
    if not ignore_path.exists():
        ignore_path.write_text(PROMPT_IGNORE_CONTENT)
        created["promptignore"] = ignore_path
    else:
        skipped["promptignore"] = ignore_path

    return {"created": created, "skipped": skipped}


def ci_status(target_dir: str = ".") -> dict[str, bool]:
    root = Path(target_dir).resolve()
    return {
        "github_actions": (root / ".github" / "workflows" / "prompt-check.yml").exists(),
        "pre_commit":     (root / ".pre-commit-config.yaml").exists(),
        "promptignore":   (root / ".promptignore").exists(),
        "is_git_repo":    (root / ".git").exists(),
    }
