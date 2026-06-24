from pathlib import Path
from typing import cast

from promptgenie.core.fileio import MAX_YAML_BYTES, safe_read_yaml

PROFILES_DIR = Path(__file__).parent.parent / "profiles"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

TARGET_KEYWORDS = {
    "claude-code": ["claude code", "claudecode", "agentic", "refactor", "codebase", "terminal"],
    "claude": ["claude", "anthropic", "sonnet", "opus", "haiku"],
    "chatgpt": ["chatgpt", "gpt", "openai", "gpt-4", "gpt-5"],
    "cursor": ["cursor", "ide", "autocomplete", "inline"],
    "gemini": ["gemini", "google", "bard", "vertex"],
    "hermes": ["hermes", "nous", "nousresearch"],
    "midjourney": ["midjourney", "image", "art", "illustration", "mj"],
    "stable-diffusion": ["stable diffusion", "sdxl", "comfyui", "diffusion"],
}

TEMPLATE_KEYWORDS = {
    "threat-model": ["threat model", "stride", "pasta", "attack", "threat"],
    "secure-code-review": ["code review", "security review", "vuln", "vulnerability", "sast"],
    "soc-triage": ["soc", "alert", "triage", "incident", "detection", "siem"],
    "pentest": ["pentest", "penetration test", "red team", "exploit"],
    "iac-review": ["iac", "terraform", "cloudformation", "infrastructure", "bicep"],
    "prompt-injection-test": ["prompt injection", "injection test", "jailbreak", "adversarial"],
    "agentic-task": ["refactor", "build", "implement", "create", "add feature", "migrate"],
}


def load_profile(target: str) -> dict:
    path = PROFILES_DIR / f"{target}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No profile found for target: {target}")
    return cast(dict, safe_read_yaml(path))


def load_template(template_name: str) -> dict:
    for tmpl_file in TEMPLATES_DIR.glob("*.yaml"):
        data = cast(dict, safe_read_yaml(tmpl_file))
        if isinstance(data, dict) and "templates" in data:
            for t in data["templates"]:
                if t.get("id") == template_name:
                    return cast(dict, t)
    raise FileNotFoundError(f"Template not found: {template_name}")


def infer_target(task: str) -> str:
    task_lower = task.lower()
    for target, keywords in TARGET_KEYWORDS.items():
        for kw in keywords:
            if kw in task_lower:
                return target
    return "claude"


def infer_template(task: str) -> str:
    task_lower = task.lower()
    for template, keywords in TEMPLATE_KEYWORDS.items():
        for kw in keywords:
            if kw in task_lower:
                return template
    return "agentic-task"


def estimate_tokens(text: str) -> int:
    # ~4 chars per token as rough estimate without requiring tiktoken import
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


def score_prompt(prompt: str, profile: dict) -> dict:
    scores = {}

    required = profile.get("required_sections", [])
    found = sum(
        1 for s in required if s.lower().replace(" ", "") in prompt.lower().replace(" ", "")
    )
    scores["target_fit"] = int((found / max(len(required), 1)) * 100)

    vague = ["help me", "fix it", "make it better", "improve", "do something"]
    clarity_penalty = sum(5 for v in vague if v in prompt.lower())
    scores["task_clarity"] = max(0, 90 - clarity_penalty)

    scores["context_sufficiency"] = 75 if len(prompt) > 300 else 50

    output_markers = ["output", "format", "return", "respond with", "json", "markdown", "list"]
    scores["output_contract"] = 90 if any(m in prompt.lower() for m in output_markers) else 55

    security_markers = ["do not", "forbidden", "stop if", "approval", "scope", "constraint"]
    security_score = min(100, 50 + sum(8 for m in security_markers if m in prompt.lower()))
    scores["safety_controls"] = security_score

    token_count = estimate_tokens(prompt)
    scores["token_efficiency"] = 95 if token_count < 800 else (80 if token_count < 1500 else 60)

    test_markers = ["test", "verify", "acceptance", "done when", "success criteria"]
    scores["testability"] = 90 if any(m in prompt.lower() for m in test_markers) else 60

    total = int(sum(scores.values()) / len(scores))
    return {"total": total, "breakdown": scores}


def generate_prompt(
    task: str,
    target: str | None = None,
    template: str | None = None,
    context: str | None = None,
    output_format: str | None = None,
    constraints: str | None = None,
    mode: str = "standard",
    best_effort: bool = False,
) -> dict:
    """Generate an optimised prompt.

    Parameters
    ----------
    best_effort:
        When *False* (default / fail-closed) a ``FileNotFoundError`` is raised if
        the requested profile or template does not exist — typos produce an explicit
        error instead of silently degraded output.

        When *True* the old lenient behaviour is preserved: missing profile/template
        fall back to built-in defaults so generation always succeeds.
    """
    if not target:
        target = infer_target(task)
    if not template:
        template = infer_template(task)

    if best_effort:
        try:
            profile = load_profile(target)
        except FileNotFoundError:
            profile = {"name": target, "required_sections": [], "forbidden_patterns": []}

        try:
            tmpl = load_template(template)
            sections = tmpl.get("sections", [])
        except FileNotFoundError:
            sections = ["Objective", "Scope", "Constraints", "Acceptance Criteria", "Output Format"]
    else:
        profile = load_profile(target)  # raises FileNotFoundError on bad target
        tmpl = load_template(template)  # raises FileNotFoundError on bad template
        sections = tmpl.get("sections", [])

    parts = []

    if mode == "minimal":
        parts.append(f"**Task:** {task}")
        if context:
            parts.append(f"**Context:** {context}")
        if constraints:
            parts.append(f"**Constraints:** {constraints}")
        output_fmt = output_format or "Clear, concise response."
        parts.append(f"**Output:** {output_fmt}")
    else:
        model_name = profile.get("name", target)
        parts.append(f"# Prompt for {model_name}\n")

        if "Objective" in sections or mode == "standard":
            parts.append(f"## Objective\n{task}")

        if context and ("Context" in sections or mode in ("standard", "exhaustive")):
            parts.append(f"## Context\n{context}")

        if "Scope" in sections or mode == "exhaustive":
            scope_note = profile.get(
                "scope_guidance", "Work only within explicitly stated boundaries."
            )
            parts.append(f"## Scope\n{scope_note}")

        if constraints and ("Constraints" in sections or mode in ("standard", "exhaustive")):
            parts.append(f"## Constraints\n{constraints}")

        forbidden = profile.get("forbidden_patterns", [])
        if forbidden and mode == "exhaustive":
            forbidden_str = "\n".join(f"- {p}" for p in forbidden)
            parts.append(f"## Forbidden Actions\n{forbidden_str}")

        security = profile.get("security_controls", [])
        if security and mode == "exhaustive":
            security_str = "\n".join(f"- {s}" for s in security)
            parts.append(f"## Security Controls\n{security_str}")

        stop_conditions = profile.get("stop_conditions", [])
        if stop_conditions and mode in ("standard", "exhaustive"):
            stop_str = "\n".join(f"- {s}" for s in stop_conditions)
            parts.append(f"## Stop Conditions\nStop and ask for approval if:\n{stop_str}")

        output_fmt = output_format or profile.get("default_output_format", "Structured markdown.")
        parts.append(f"## Output Format\n{output_fmt}")

        if "Acceptance Criteria" in sections or mode == "exhaustive":
            parts.append(
                "## Acceptance Criteria\nDone when:\n- All objectives are met\n- Output matches the requested format\n- No forbidden actions were taken"
            )

    prompt_text = "\n\n".join(parts)

    token_estimate = estimate_tokens(prompt_text)
    scores = score_prompt(prompt_text, profile)

    return {
        "prompt": prompt_text,
        "target": target,
        "template": template,
        "mode": mode,
        "token_estimate": token_estimate,
        "score": scores,
    }


def list_targets() -> list[dict]:
    targets = []
    for f in sorted(PROFILES_DIR.glob("*.yaml")):
        data = safe_read_yaml(f, max_bytes=MAX_YAML_BYTES)
        targets.append(
            {
                "id": f.stem,
                "name": data.get("name", f.stem),
                "category": data.get("category", ""),
                "strengths": data.get("strengths", []),
            }
        )
    return targets


def list_templates() -> list[dict]:
    templates = []
    for f in sorted(TEMPLATES_DIR.glob("*.yaml")):
        data = safe_read_yaml(f, max_bytes=MAX_YAML_BYTES)
        if isinstance(data, dict) and "templates" in data:
            for t in data["templates"]:
                templates.append(
                    {
                        "id": t.get("id", ""),
                        "name": t.get("name", ""),
                        "category": t.get("category", ""),
                        "description": t.get("description", ""),
                    }
                )
    return templates
