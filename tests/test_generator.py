"""Tests for promptgenie.core.generator."""

from promptgenie.core.generator import (
    estimate_tokens,
    generate_prompt,
    infer_target,
    infer_template,
    list_targets,
    list_templates,
    load_profile,
    score_prompt,
)


class TestInference:
    def test_infers_claude_code_from_refactor(self):
        assert infer_target("refactor the auth module") == "claude-code"

    def test_infers_claude_as_default(self):
        assert infer_target("write a poem") == "claude"

    def test_infers_chatgpt(self):
        assert infer_target("use chatgpt to explain this") == "chatgpt"

    def test_infers_threat_model_template(self):
        assert infer_template("threat model the payment API") == "threat-model"

    def test_infers_agentic_task_as_default(self):
        assert infer_template("build a login page") == "agentic-task"

    def test_infers_iac_review(self):
        assert infer_template("review the terraform config") == "iac-review"


class TestGeneratePrompt:
    def test_returns_dict_with_prompt(self):
        result = generate_prompt("refactor auth", target="claude-code")
        assert "prompt" in result
        assert isinstance(result["prompt"], str)
        assert len(result["prompt"]) > 0

    def test_includes_objective_section(self):
        result = generate_prompt("refactor auth", target="claude-code")
        assert "## Objective" in result["prompt"]

    def test_includes_stop_conditions_for_claude_code(self):
        result = generate_prompt("refactor auth", target="claude-code", mode="standard")
        assert "Stop" in result["prompt"]

    def test_exhaustive_mode_includes_forbidden_actions(self):
        result = generate_prompt("refactor auth", target="claude-code", mode="exhaustive")
        assert "Forbidden" in result["prompt"]

    def test_minimal_mode_is_shorter_than_exhaustive(self):
        minimal = generate_prompt("refactor auth", target="claude-code", mode="minimal")
        exhaustive = generate_prompt("refactor auth", target="claude-code", mode="exhaustive")
        assert minimal["token_estimate"] < exhaustive["token_estimate"]

    def test_context_is_included(self):
        result = generate_prompt("refactor auth", target="claude", context="Django app")
        assert "Django app" in result["prompt"]

    def test_returns_score_dict(self):
        result = generate_prompt("refactor auth", target="claude-code")
        assert "score" in result
        assert "total" in result["score"]
        assert "breakdown" in result["score"]

    def test_returns_token_estimate(self):
        result = generate_prompt("refactor auth", target="claude-code")
        assert result["token_estimate"] > 0

    def test_target_and_template_in_result(self):
        result = generate_prompt("refactor auth", target="claude-code", template="agentic-task")
        assert result["target"] == "claude-code"
        assert result["template"] == "agentic-task"


class TestListTargets:
    def test_returns_list(self):
        targets = list_targets()
        assert isinstance(targets, list)
        assert len(targets) > 0

    def test_each_target_has_id_and_name(self):
        for t in list_targets():
            assert "id" in t
            assert "name" in t

    def test_known_profiles_present(self):
        ids = [t["id"] for t in list_targets()]
        assert "claude" in ids
        assert "claude-code" in ids
        assert "chatgpt" in ids


class TestListTemplates:
    def test_returns_list(self):
        templates = list_templates()
        assert isinstance(templates, list)
        assert len(templates) > 0

    def test_each_template_has_id_and_name(self):
        for t in list_templates():
            assert "id" in t
            assert "name" in t

    def test_known_templates_present(self):
        ids = [t["id"] for t in list_templates()]
        assert "threat-model" in ids
        assert "agentic-task" in ids


class TestScoring:
    def test_score_is_0_to_100(self):
        profile = load_profile("claude-code")
        prompt = "## Objective\nRefactor auth.\n## Stop Conditions\nStop if uncertain."
        score = score_prompt(prompt, profile)
        assert 0 <= score["total"] <= 100

    def test_score_has_all_dimensions(self):
        profile = load_profile("claude-code")
        score = score_prompt("test", profile)
        dims = {
            "target_fit",
            "task_clarity",
            "context_sufficiency",
            "output_contract",
            "safety_controls",
            "token_efficiency",
            "testability",
        }
        assert set(score["breakdown"].keys()) == dims


class TestEstimateTokens:
    def test_returns_positive_int(self):
        assert estimate_tokens("Hello world") > 0

    def test_longer_text_has_more_tokens(self):
        short = estimate_tokens("Hi")
        long = estimate_tokens("Hi " * 100)
        assert long > short
