from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.api.deps import COOKIE_NAME
from app.config import get_settings
from app.core.security import create_access_token, verify_password

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/api/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response) -> LoginResponse:
    settings = get_settings()
    valid_user = payload.username == settings.dashboard_username
    # Always run the hash comparison, even for a wrong username (there's only one
    # account either way), so response timing doesn't leak whether the username matched.
    password_ok = verify_password(payload.password, settings.dashboard_password_hash)
    if not (valid_user and password_ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    token = create_access_token(subject=payload.username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
    )
    return LoginResponse(access_token=token)


@router.post("/api/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}
