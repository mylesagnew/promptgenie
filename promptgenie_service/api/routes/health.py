from fastapi import APIRouter, HTTPException

from promptgenie.core.config import load_config
from promptgenie_service.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict:
    """Process is up. Never depends on external state."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> dict:
    """Config is loadable. Extend with DB/queue/storage checks as those land."""
    settings = get_settings()
    try:
        load_config(settings.config_path)
    except (FileNotFoundError, ValueError) as exc:
        # Unauthenticated route, so the error (which can name file paths) stays out of the response.
        raise HTTPException(status_code=503, detail="config not ready") from exc
    return {"status": "ok"}
