"""The one control that moves real money — built and gated deliberately.

Two independent checks must both pass before the bot will place a live order:
1. This app-level switch (`bot_config.mode`), which requires re-entering the
   dashboard password AND typing an exact confirmation phrase (not a checkbox).
2. The `BROKER_LIVE_ACCOUNT_CONFIRMED` Railway environment variable actually being
   true — something only the operator can set outside the running app. Unlike
   OANDA (a simple practice/live base-URL swap), MT5's demo-vs-live distinction is a
   property of WHICH account `METAAPI_ACCOUNT_ID` points to, not a togglable API
   setting — this flag is a manual, operator-set assertion of that fact, playing the
   same "infra-level gate the app can't flip on its own" role.
Either check alone is not enough. A dashboard-only compromise can't move real money
without the env var also confirming a live account; the env var alone can't either,
since the app still defaults to practice mode until this endpoint is exercised.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_notifier
from app.config import get_settings
from app.core.enums import BotMode
from app.core.security import verify_password
from app.db import crud

router = APIRouter()

REQUIRED_PHRASE = "SWITCH TO LIVE TRADING"


class RequestLivePayload(BaseModel):
    confirmation_phrase: str
    password: str


@router.post("/api/mode/request-live")
async def request_live(
    payload: RequestLivePayload,
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    notify=Depends(get_notifier),
):
    settings = get_settings()
    if payload.confirmation_phrase.strip() != REQUIRED_PHRASE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f'Confirmation phrase must be exactly: "{REQUIRED_PHRASE}"')
    if not verify_password(payload.password, settings.dashboard_password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Password incorrect")
    if not settings.broker_live_account_confirmed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "BROKER_LIVE_ACCOUNT_CONFIRMED is not set to true in this deployment's environment variables. "
            "Set it only after verifying METAAPI_ACCOUNT_ID points to a genuinely live MT5 account, then "
            "redeploy — this dashboard switch alone cannot enable live trading.",
        )

    config = await crud.update_bot_config(db, mode=BotMode.LIVE)
    await notify("🚨 LIVE TRADING ENABLED via dashboard. The bot will now place real orders.")
    return {"mode": config.mode}


@router.post("/api/mode/revert-practice")
async def revert_practice(
    user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db), notify=Depends(get_notifier)
):
    config = await crud.update_bot_config(db, mode=BotMode.PRACTICE)
    await notify("✅ Reverted to practice mode.")
    return {"mode": config.mode}
