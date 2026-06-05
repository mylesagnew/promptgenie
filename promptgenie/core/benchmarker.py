"""
benchmarker.py — run a prompt against a Claude model and score the output.

Rubric dimensions (each 0-100, averaged to an overall score):

  relevance       Did the output address the prompt objective?
  completeness    Did the output cover all required sections/tasks?
  format          Did the output match the requested format?
  safety          Did the output respect constraints and forbidden actions?
  conciseness     Was the output free of padding and unnecessary repetition?
  actionability   Is the output specific and immediately usable?

The rubric is evaluated by a second Claude call (judge model), keeping the
benchmark model and judge model separate so results are comparable across runs.

Output includes:
  - model response text
  - rubric scores (per dimension + overall)
  - token usage (input / output / cache read / cache write)
  - estimated cost
  - latency
  - comparison table when multiple runs given
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

JUDGE_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MODEL = "claude-sonnet-4-6"

# Approximate cost per million tokens (USD) — update as pricing changes
COST_PER_M = {
    "claude-opus-4-8": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-haiku-4-5-20251001": {
        "input": 0.8,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_write": 1.0,
    },
}

RUBRIC_DIMENSIONS = [
    "relevance",
    "completeness",
    "format_compliance",
    "safety_compliance",
    "conciseness",
    "actionability",
]

JUDGE_SYSTEM = """You are an expert prompt quality evaluator. You will be given:
1. A prompt that was sent to an AI model.
2. The model's response to that prompt.

Score the response on each of the following dimensions from 0 to 100:

- relevance: Did the response directly address the prompt's objective?
- completeness: Did it cover all tasks, sections, or requirements stated in the prompt?
- format_compliance: Did it match the output format requested in the prompt?
- safety_compliance: Did it respect all constraints, forbidden actions, and stop conditions?
- conciseness: Was the response free of padding, repetition, and unnecessary filler?
- actionability: Is the output specific, concrete, and immediately usable?

Respond ONLY with a JSON object in exactly this format:
{
  "relevance": <0-100>,
  "completeness": <0-100>,
  "format_compliance": <0-100>,
  "safety_compliance": <0-100>,
  "conciseness": <0-100>,
  "actionability": <0-100>,
  "reasoning": "<one sentence per dimension, pipe-separated>"
}"""


@dataclass
class BenchmarkRun:
    model: str
    prompt_path: str
    prompt_text: str
    response_text: str
    rubric_scores: dict[str, int] = field(default_factory=dict)
    reasoning: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_s: float = 0.0
    estimated_cost_usd: float = 0.0

    @property
    def overall_score(self) -> int:
        if not self.rubric_scores:
            return 0
        return int(sum(self.rubric_scores.values()) / len(self.rubric_scores))

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _estimate_cost(
    model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int
) -> float:
    rates = COST_PER_M.get(model, COST_PER_M[DEFAULT_MODEL])
    return (
        input_tokens * rates["input"] / 1_000_000
        + output_tokens * rates["output"] / 1_000_000
        + cache_read * rates["cache_read"] / 1_000_000
        + cache_write * rates["cache_write"] / 1_000_000
    )


def _call_model(client, model: str, prompt: str, system: str | None = None) -> tuple[str, dict]:
    """Call Claude and return (response_text, usage_dict)."""
    messages = [{"role": "user", "content": prompt}]
    kwargs = {"model": model, "max_tokens": 4096, "messages": messages}
    if system:
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    response = client.messages.create(**kwargs)
    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    usage = {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
        "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    }
    return text, usage


def _judge(client, prompt_text: str, response_text: str) -> tuple[dict, str]:
    """Ask the judge model to score the response. Returns (scores_dict, reasoning)."""
    import json
    import re

    judge_prompt = f"""<prompt>
{prompt_text}
</prompt>

<response>
{response_text}
</response>

Score the response on all six dimensions and return the JSON object."""

    raw, _ = _call_model(client, JUDGE_MODEL, judge_prompt, system=JUDGE_SYSTEM)

    # Extract JSON from response
    match = re.search(r"\{[\s\S]+\}", raw)
    if not match:
        return dict.fromkeys(RUBRIC_DIMENSIONS, 50), "Could not parse judge response."

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return dict.fromkeys(RUBRIC_DIMENSIONS, 50), "Invalid JSON from judge."

    scores = {d: min(100, max(0, int(parsed.get(d, 50)))) for d in RUBRIC_DIMENSIONS}
    reasoning = parsed.get("reasoning", "")
    return scores, reasoning


def run_benchmark(
    prompt_path: str,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    runs: int = 1,
) -> list[BenchmarkRun]:
    """Run prompt against model N times and return scored BenchmarkRun list."""
    import anthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set. Pass --api-key or export the env var.")

    client = anthropic.Anthropic(api_key=key)
    prompt_text = Path(prompt_path).read_text()
    results: list[BenchmarkRun] = []

    for _i in range(runs):
        t0 = time.monotonic()
        response_text, usage = _call_model(client, model, prompt_text)
        latency = time.monotonic() - t0

        scores, reasoning = _judge(client, prompt_text, response_text)
        cost = _estimate_cost(
            model, usage["input"], usage["output"], usage["cache_read"], usage["cache_write"]
        )

        results.append(
            BenchmarkRun(
                model=model,
                prompt_path=prompt_path,
                prompt_text=prompt_text,
                response_text=response_text,
                rubric_scores=scores,
                reasoning=reasoning,
                input_tokens=usage["input"],
                output_tokens=usage["output"],
                cache_read_tokens=usage["cache_read"],
                cache_write_tokens=usage["cache_write"],
                latency_s=round(latency, 2),
                estimated_cost_usd=round(cost, 6),
            )
        )

    return results


def compare_benchmarks(runs_a: list[BenchmarkRun], runs_b: list[BenchmarkRun]) -> dict:
    """Average scores across multiple runs for two prompts and return comparison."""

    def avg(runs: list[BenchmarkRun]) -> dict:
        if not runs:
            return {}
        dims = RUBRIC_DIMENSIONS
        return {
            "overall": int(sum(r.overall_score for r in runs) / len(runs)),
            "scores": {
                d: int(sum(r.rubric_scores.get(d, 0) for r in runs) / len(runs)) for d in dims
            },
            "avg_tokens": int(sum(r.total_tokens for r in runs) / len(runs)),
            "avg_latency": round(sum(r.latency_s for r in runs) / len(runs), 2),
            "avg_cost": round(sum(r.estimated_cost_usd for r in runs) / len(runs), 6),
        }

    a = avg(runs_a)
    b = avg(runs_b)
    return {"a": a, "b": b}
