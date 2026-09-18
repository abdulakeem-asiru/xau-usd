from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import get_optional_user
from app.config import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/login")
async def login_page(request: Request):
    if await get_optional_user(request) is not None:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(request, "login.html", {})


@router.get("/")
async def root(request: Request):
    return RedirectResponse("/dashboard")


@router.get("/dashboard")
async def dashboard_page(request: Request, user: str | None = Depends(get_optional_user)):
    if user is None:
        return RedirectResponse("/login")
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"instrument": settings.instrument, "broker_live_account_confirmed": settings.broker_live_account_confirmed},
    )


@router.get("/backtest")
async def backtest_page(request: Request, user: str | None = Depends(get_optional_user)):
    if user is None:
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "backtest.html", {})
