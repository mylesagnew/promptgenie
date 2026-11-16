from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from promptgenie.core.generator import generate_prompt
from promptgenie.core.linter import lint
from promptgenie.core.scanner import scan
from promptgenie_service.api.routes._shared import resolve_config

router = APIRouter(prefix="/v1", tags=["generate"])


class GenerateRequest(BaseModel):
    task: str = Field(..., min_length=1)
    # generate_prompt joins target into a profile file path, so it must stay a bare name.
    target: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    template: str | None = None
    context: str | None = None
    output_format: str | None = None
    constraints: str | None = None
    mode: Literal["minimal", "standard", "exhaustive"] = "standard"
    best_effort: bool = False
    no_config: bool = False
    include_lint: bool = True
    include_scan: bool = True


class GenerateResponse(BaseModel):
    prompt: str
    target: str
    template: str
    mode: str
    token_estimate: int
    score: dict
    lint: dict | None = None
    scan: dict | None = None


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    try:
        cfg = resolve_config(req.no_config, req.best_effort)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = generate_prompt(
            task=req.task,
            target=req.target,
            template=req.template,
            context=req.context,
            output_format=req.output_format,
            constraints=req.constraints,
            mode=req.mode,
            best_effort=req.best_effort,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prompt_text = result["prompt"]

    lint_payload = None
    if req.include_lint:
        lint_result = lint(prompt_text, config=cfg.linter)
        lint_payload = {
            "score": lint_result.score,
            "issues": [asdict(issue) for issue in lint_result.issues],
        }

    scan_payload = None
    if req.include_scan:
        scan_result = scan(prompt_text, config=cfg.scanner)
        scan_payload = {
            "risk_level": scan_result.risk_level,
            "findings": [asdict(finding) for finding in scan_result.findings],
        }

    return GenerateResponse(
        prompt=prompt_text,
        target=result["target"],
        template=result["template"],
        mode=req.mode,
        token_estimate=result["token_estimate"],
        score=result["score"],
        lint=lint_payload,
        scan=scan_payload,
    )
