from importlib.metadata import version

from fastapi import Depends, FastAPI

from promptgenie_service.api.auth import require_api_key
from promptgenie_service.api.routes import generate, health, lint

app = FastAPI(
    title="promptgenie-api",
    version=version("promptgenie"),
    description="HTTP adapter over promptgenie.core (generate, lint). CLI-equivalent, no business logic here.",
)

app.include_router(health.router)
app.include_router(generate.router, dependencies=[Depends(require_api_key)])
app.include_router(lint.router, dependencies=[Depends(require_api_key)])
