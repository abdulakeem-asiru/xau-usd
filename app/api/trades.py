from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db import crud
from app.db.models import Trade

router = APIRouter()


def trade_to_dict(t: Trade) -> dict:
    return {
        "id": t.id,
        "broker_trade_id": t.broker_trade_id,
        "instrument": t.instrument,
        "side": t.side,
        "volume": float(t.volume),
        "entry_price": float(t.entry_price) if t.entry_price is not None else None,
        "stop_loss_price": float(t.stop_loss_price),
        "take_profit_price": float(t.take_profit_price) if t.take_profit_price is not None else None,
        "trailing_stop_distance": float(t.trailing_stop_distance) if t.trailing_stop_distance is not None else None,
        "exit_price": float(t.exit_price) if t.exit_price is not None else None,
        "status": t.status,
        "close_reason": t.close_reason,
        "pnl": float(t.pnl) if t.pnl is not None else None,
        "risk_amount": float(t.risk_amount) if t.risk_amount is not None else None,
        "strategy_name": t.strategy_name,
        "signal_reason": t.signal_reason,
        "mode": t.mode,
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }


@router.get("/api/trades")
async def list_trades(
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    trades = await crud.list_trades(db, status=status_filter, limit=limit, offset=offset)
    return [trade_to_dict(t) for t in trades]


@router.get("/api/trades/{trade_id}")
async def get_trade(trade_id: int, user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    trade = await crud.get_trade(db, trade_id)
    if trade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")
    return trade_to_dict(trade)
