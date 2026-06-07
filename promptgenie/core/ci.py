"""
ci.py — scaffold GitHub Actions and pre-commit hooks for prompt quality gates.

promptgenie ci init           — sets up .github/workflows/prompt-check.yml
                                and .pre-commit-config.yaml in the current dir
promptgenie ci status         — check what CI integrations are active
"""

from pathlib import Path

from promptgenie.core.fileio import safe_write_text

_CHECKOUT_SHA = "34e114876b0b11c390a56381ad16ebd13914f8d5"  # actions/checkout v4
_SETUP_UV_SHA = "d0cc045d04ccac9d8b7881df0226f9e82c39688e"  # astral-sh/setup-uv v6


def _workflow_content() -> str:
    """Build the scaffold workflow content, pinning the current installed version."""
    try:
        from importlib.metadata import version as _v

        pg_version = _v("promptgenie")
    except Exception:
        pg_version = "latest"

    return f"""\
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

permissions:
  contents: read

jobs:
  prompt-lint:
    name: Lint prompt files
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{_CHECKOUT_SHA} # v4
      - uses: astral-sh/setup-uv@{_SETUP_UV_SHA} # v6
        with:
          python-version: '3.11'
      - name: Install PromptGenie
        run: uv pip install --system "promptgenie=={pg_version}"
      - name: Lint prompt files
        run: |
          FAILED=0
          while IFS= read -r file; do
            echo "Linting: $file"
            promptgenie lint "$file" || FAILED=1
          done < <(find . -not -path './.git/*' -not -path './.venv/*' \\
            \\( -name '*.prompt.md' -o -name '*.md' \\) \\
            | grep -v README | grep -v CHANGELOG | grep -v LICENSE)
          exit $FAILED

  prompt-scan:
    name: Security scan prompt files
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{_CHECKOUT_SHA} # v4
      - uses: astral-sh/setup-uv@{_SETUP_UV_SHA} # v6
        with:
          python-version: '3.11'
      - name: Install PromptGenie
        run: uv pip install --system "promptgenie=={pg_version}"
      - name: Scan prompt files
        run: |
          FAILED=0
          while IFS= read -r file; do
            echo "Scanning: $file"
            promptgenie scan "$file" || FAILED=1
          done < <(find . -not -path './.git/*' -not -path './.venv/*' \\
            \\( -name '*.prompt.md' -o -name '*.md' \\) \\
            | grep -v README | grep -v CHANGELOG | grep -v LICENSE)
          exit $FAILED

  prompt-test:
    name: Run prompt test suites
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{_CHECKOUT_SHA} # v4
      - uses: astral-sh/setup-uv@{_SETUP_UV_SHA} # v6
        with:
          python-version: '3.11'
      - name: Install PromptGenie
        run: uv pip install --system "promptgenie=={pg_version}"
      - name: Run test suites
        run: |
          FAILED=0
          while IFS= read -r file; do
            echo "Testing: $file"
            promptgenie test "$file" || FAILED=1
          done < <(find . -not -path './.git/*' -name '*.prompt-test.yaml')
          exit $FAILED
"""


WORKFLOW_CONTENT = _workflow_content()

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


def init_ci(target_dir: str = ".") -> dict[str, dict[str, Path]]:
    root = Path(target_dir).resolve()
    created: dict[str, Path] = {}
    skipped: dict[str, Path] = {}

    # GitHub Actions workflow
    gha_dir = root / ".github" / "workflows"
    gha_dir.mkdir(parents=True, exist_ok=True)
    gha_path = gha_dir / "prompt-check.yml"
    if not gha_path.exists():
        safe_write_text(gha_path, WORKFLOW_CONTENT, force=False)
        created["github_actions"] = gha_path
    else:
        skipped["github_actions"] = gha_path

    # Pre-commit config
    precommit_path = root / ".pre-commit-config.yaml"
    if not precommit_path.exists():
        safe_write_text(precommit_path, PRE_COMMIT_CONTENT, force=False)
        created["pre_commit"] = precommit_path
    else:
        skipped["pre_commit"] = precommit_path

    # .promptignore
    ignore_path = root / ".promptignore"
    if not ignore_path.exists():
        safe_write_text(ignore_path, PROMPT_IGNORE_CONTENT, force=False)
        created["promptignore"] = ignore_path
    else:
        skipped["promptignore"] = ignore_path

    return {"created": created, "skipped": skipped}


def ci_status(target_dir: str = ".") -> dict[str, bool]:
    root = Path(target_dir).resolve()
    return {
        "github_actions": (root / ".github" / "workflows" / "prompt-check.yml").exists(),
        "pre_commit": (root / ".pre-commit-config.yaml").exists(),
        "promptignore": (root / ".promptignore").exists(),
        "is_git_repo": (root / ".git").exists(),
    }
