import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_broker, get_current_user, get_db, get_notifier
from app.core.enums import CloseReason, TradeStatus
from app.db import crud

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/kill-switch")
async def kill_switch(
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    broker=Depends(get_broker),
    notify=Depends(get_notifier),
):
    await crud.update_bot_config(db, is_paused=True)
    open_trades = await crud.get_open_trades(db)
    closed_ids = []
    failed_ids = []
    contract_sizes: dict[str, float] = {}
    for trade in open_trades:
        try:
            fill_price = await broker.close_position(trade.broker_trade_id)
        except Exception:
            logger.exception("Kill switch: failed to close trade #%s at broker", trade.id)
            failed_ids.append(trade.id)
            continue
        if trade.instrument not in contract_sizes:
            spec = await broker.get_symbol_specification(trade.instrument)
            contract_sizes[trade.instrument] = spec.contract_size
        diff = fill_price - float(trade.entry_price) if trade.side == "buy" else float(trade.entry_price) - fill_price
        pnl = diff * float(trade.volume) * contract_sizes[trade.instrument]
        await crud.update_trade(
            db,
            trade,
            status=TradeStatus.CLOSED,
            exit_price=fill_price,
            pnl=pnl,
            close_reason=CloseReason.KILL_SWITCH,
            closed_at=datetime.now(timezone.utc),
        )
        closed_ids.append(trade.id)

    message = f"🛑 KILL SWITCH activated from dashboard — closed {len(closed_ids)} position(s), bot paused."
    if failed_ids:
        message += f" WARNING: failed to close trade(s) {failed_ids} — check your MT5 terminal directly."
    await notify(message)
    return {"paused": True, "closed_trade_ids": closed_ids, "failed_trade_ids": failed_ids}
