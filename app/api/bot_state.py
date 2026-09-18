from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_broker, get_current_user, get_db, get_notifier
from app.db import crud

router = APIRouter()


@router.get("/api/config/bot-state")
async def get_bot_state(
    user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db), broker=Depends(get_broker)
):
    config = await crud.get_bot_config(db)
    account = await broker.get_account_summary()
    breaker_row = await crud.get_or_create_todays_circuit_breaker(db, account.equity)
    open_trades = await crud.get_open_trades(db)
    return {
        "is_running": config.is_running,
        "is_paused": config.is_paused,
        "mode": config.mode,
        "balance": float(account.balance),
        "equity": float(account.equity),
        "open_positions_count": len(open_trades),
        "today_realized_pnl": float(breaker_row.realized_pnl_today),
        "halted": breaker_row.halted,
        "halted_reason": breaker_row.halted_reason,
    }


@router.post("/api/bot/pause")
async def pause_bot(
    user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db), notify=Depends(get_notifier)
):
    config = await crud.update_bot_config(db, is_paused=True)
    await notify("⏸ Bot paused from dashboard — no new entries will be opened.")
    return {"is_paused": config.is_paused}


@router.post("/api/bot/resume")
async def resume_bot(
    user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db), notify=Depends(get_notifier)
):
    config = await crud.update_bot_config(db, is_paused=False)
    await notify("▶️ Bot resumed from dashboard.")
    return {"is_paused": config.is_paused}
