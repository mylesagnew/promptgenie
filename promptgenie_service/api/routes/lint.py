from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from promptgenie.core.linter import lint as run_lint
from promptgenie_service.api.routes._shared import resolve_config

router = APIRouter(prefix="/v1", tags=["lint"])


class LintRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    no_config: bool = False
    best_effort: bool = False


class LintResponse(BaseModel):
    score: int
    issues: list[dict]


@router.post("/lint", response_model=LintResponse)
def lint_endpoint(req: LintRequest) -> LintResponse:
    try:
        cfg = resolve_config(req.no_config, req.best_effort)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = run_lint(req.prompt, config=cfg.linter)
    return LintResponse(score=result.score, issues=[asdict(issue) for issue in result.issues])
