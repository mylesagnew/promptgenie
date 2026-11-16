import secrets
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from promptgenie_service.settings import get_settings

_bearer = HTTPBearer(auto_error=False)


def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Require ``Authorization: Bearer <PROMPTGENIE_API_KEY>``.

    Fails closed: with no key configured every request is refused, so a
    deployment that forgets the variable is unusable rather than open.
    """
    configured = get_settings().api_key
    expected = configured.get_secret_value() if configured else ""
    if not expected:
        raise HTTPException(status_code=503, detail="PROMPTGENIE_API_KEY is not configured")
    supplied = credentials.credentials if credentials else ""
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
