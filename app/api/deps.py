from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token
from app.db.base import get_db

__all__ = ["get_db", "get_current_user", "get_optional_user", "get_broker", "get_notifier"]

COOKIE_NAME = "access_token"

# auto_error=False: browser page loads carry the JWT as a cookie, not a bearer header —
# this dependency only extracts an Authorization header when one is present.
bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is not None:
        return credentials.credentials
    return request.cookies.get(COOKIE_NAME)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> str:
    """For /api/* JSON routes — raises 401 on missing/invalid auth."""
    token = _extract_token(request, credentials)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    subject = decode_access_token(token)
    if subject is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return subject


async def get_optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> str | None:
    """For server-rendered page routes — returns None instead of raising, so the route
    can redirect to /login instead of showing a JSON error page to a browser navigation.
    """
    token = _extract_token(request, credentials)
    if token is None:
        return None
    return decode_access_token(token)


def get_broker(request: Request):
    return request.app.state.broker


def get_notifier(request: Request):
    return request.app.state.notify
