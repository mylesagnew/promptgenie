"""validate command — check all YAML config artefacts for schema correctness."""

import sys
from pathlib import Path

import click
import yaml

from promptgenie.models import Profile, Template, ValidationResult
from promptgenie.renderers.rich import console


def _validate_profile(path: Path) -> ValidationResult:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        return ValidationResult(path=path, kind="profile", valid=False, errors=[str(exc)])
    profile = Profile.from_dict(data, profile_id=path.stem)
    errors = profile.validate()
    if not isinstance(data, dict):
        errors.append("Profile must be a YAML mapping.")
    return ValidationResult(path=path, kind="profile", valid=not errors, errors=errors)


def _validate_template_file(path: Path) -> list[ValidationResult]:
    results = []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        return [ValidationResult(path=path, kind="template", valid=False, errors=[str(exc)])]
    templates = data.get("templates", []) if isinstance(data, dict) else []
    if not templates:
        results.append(
            ValidationResult(
                path=path,
                kind="template",
                valid=False,
                errors=["No 'templates' list found in file."],
            )
        )
        return results
    for tmpl_data in templates:
        tmpl = Template.from_dict(tmpl_data)
        errors = tmpl.validate()
        results.append(
            ValidationResult(
                path=path,
                kind="template",
                valid=not errors,
                errors=errors,
            )
        )
    return results


def _validate_context_pack(path: Path) -> ValidationResult:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        return ValidationResult(path=path, kind="context-pack", valid=False, errors=[str(exc)])
    errors = []
    if not isinstance(data, dict):
        errors.append("Context pack must be a YAML mapping.")
    elif not data.get("name"):
        errors.append("Context pack 'name' is required.")
    return ValidationResult(path=path, kind="context-pack", valid=not errors, errors=errors)


def _validate_workflow_file(path: Path) -> ValidationResult:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        return ValidationResult(path=path, kind="workflow", valid=False, errors=[str(exc)])

    from promptgenie.core.workflow import WorkflowStep, WorkflowValidationError, validate_workflow

    errors = []
    if not isinstance(data, dict):
        errors.append("Workflow must be a YAML mapping.")
        return ValidationResult(path=path, kind="workflow", valid=False, errors=errors)

    raw_steps = data.get("steps", [])
    steps = [
        WorkflowStep(
            id=s.get("id", ""),
            name=s.get("name", ""),
            objective=s.get("objective", ""),
            depends_on=s.get("depends_on"),
        )
        for s in raw_steps
        if isinstance(s, dict)
    ]
    try:
        validate_workflow(steps)
    except WorkflowValidationError as exc:
        errors.append(str(exc))

    return ValidationResult(path=path, kind="workflow", valid=not errors, errors=errors)


def _validate_prompt_test(path: Path) -> ValidationResult:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        return ValidationResult(path=path, kind="prompt-test", valid=False, errors=[str(exc)])
    errors = []
    warnings = []
    if not isinstance(data, dict):
        errors.append("Prompt test suite must be a YAML mapping.")
        return ValidationResult(path=path, kind="prompt-test", valid=False, errors=errors)
    if not data.get("prompt"):
        errors.append("Field 'prompt' (path to prompt file) is required.")
    if not data.get("tests"):
        warnings.append("No 'tests' list found — suite will pass trivially.")
    return ValidationResult(
        path=path, kind="prompt-test", valid=not errors, errors=errors, warnings=warnings
    )


@click.command(name="validate")
@click.argument("paths", nargs=-1, type=click.Path())
@click.option(
    "--all",
    "validate_all",
    is_flag=True,
    default=False,
    help="Validate all built-in profiles, templates, and context packs.",
)
def validate_cmd(paths, validate_all):
    """Validate YAML config files (profiles, templates, context packs, workflows, prompt tests)."""
    from promptgenie.core.context_packs import PACKS_DIR
    from promptgenie.core.generator import PROFILES_DIR, TEMPLATES_DIR

    results: list[ValidationResult] = []

    if validate_all:
        for p in sorted(PROFILES_DIR.glob("*.yaml")):
            results.append(_validate_profile(p))
        for p in sorted(TEMPLATES_DIR.glob("*.yaml")):
            results.extend(_validate_template_file(p))
        for p in sorted(PACKS_DIR.glob("*.yaml")):
            results.append(_validate_context_pack(p))

    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            results.append(
                ValidationResult(
                    path=path, kind="unknown", valid=False, errors=[f"File not found: {path}"]
                )
            )
            continue
        name = path.name.lower()
        if name.endswith(".prompt-test.yaml") or name.endswith(".prompt-test.yml"):
            results.append(_validate_prompt_test(path))
        elif name.endswith(".workflow.yaml") or name.endswith(".workflow.yml"):
            results.append(_validate_workflow_file(path))
        elif "profile" in str(path) or path.parent.name == "profiles":
            results.append(_validate_profile(path))
        elif "template" in str(path) or path.parent.name == "templates":
            results.extend(_validate_template_file(path))
        elif "context-pack" in str(path) or path.parent.name == "context-packs":
            results.append(_validate_context_pack(path))
        else:
            # Best-effort: try as workflow, then prompt-test, then context pack
            data = {}
            try:
                import yaml as _yaml

                data = _yaml.safe_load(path.read_text()) or {}
            except Exception:
                pass
            if isinstance(data, dict) and "steps" in data:
                results.append(_validate_workflow_file(path))
            elif isinstance(data, dict) and "tests" in data:
                results.append(_validate_prompt_test(path))
            else:
                results.append(_validate_context_pack(path))

    if not results:
        console.print("[dim]Nothing to validate. Use --all or pass file paths.[/dim]")
        return

    errors_total = 0
    for r in results:
        color = "green" if r.valid else "red"
        status = "✓" if r.valid else "✗"
        console.print(f"[{color}]{status}[/{color}] [{r.kind}] {r.path}")
        for e in r.errors:
            console.print(f"  [red]ERROR:[/red] {e}")
            errors_total += 1
        for w in r.warnings:
            console.print(f"  [yellow]WARN:[/yellow]  {w}")

    console.print()
    if errors_total:
        console.print(
            f"[red]Validation failed:[/red] {errors_total} error(s) in {len(results)} file(s)."
        )
        sys.exit(1)
    else:
        console.print(f"[green]All {len(results)} file(s) valid.[/green]")
