"""Reconciliation between the broker (source of truth for what's actually open) and our
local `trades` table. Run once at startup (Railway restarts this container on every
deploy) AND at the top of every live-loop tick — a stop-loss/take-profit can fire at
the broker between ticks just as easily as while the process is down, and without
this the DB would show a phantom "open" position forever, the dashboard would be
wrong, and the circuit breaker would never see the resulting loss.
"""
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.interface import BrokerProtocol
from app.core.enums import CloseReason, TradeStatus
from app.db import crud
from app.db.models import Trade

logger = logging.getLogger(__name__)

Notifier = Callable[[str], Awaitable[None]]


async def _noop_notifier(_message: str) -> None:
    return None


noop_notifier: Notifier = _noop_notifier


def _infer_close_reason(trade: Trade, close_price: float | None) -> str:
    if close_price is None:
        return CloseReason.MANUAL
    sl = float(trade.stop_loss_price)
    tp = float(trade.take_profit_price) if trade.take_profit_price is not None else None
    dist_to_sl = abs(close_price - sl)
    if tp is not None and abs(close_price - tp) < dist_to_sl:
        return CloseReason.TP_HIT
    return CloseReason.SL_HIT if dist_to_sl < abs(close_price - float(trade.entry_price or close_price)) else CloseReason.MANUAL


async def _close_from_broker_record(db: AsyncSession, broker: BrokerProtocol, trade: Trade, notify: Notifier) -> float:
    """Fetches the real close price/PnL for a trade the broker no longer lists as open,
    and updates the DB row to match. Returns realized PnL (0.0 if the lookup fails).
    """
    try:
        detail = await broker.get_trade(trade.broker_trade_id)
    except Exception:
        logger.exception("Failed to fetch closed trade detail for #%s (broker id %s)", trade.id, trade.broker_trade_id)
        await crud.update_trade(
            db, trade, status=TradeStatus.CLOSED, close_reason=CloseReason.MANUAL, closed_at=datetime.now(timezone.utc)
        )
        await notify(
            f"⚠️ Trade #{trade.id} disappeared from open positions but its close details couldn't be fetched — "
            f"check your MT5 account's history for the exact fill/PnL."
        )
        return 0.0

    close_reason = _infer_close_reason(trade, detail.close_price)
    await crud.update_trade(
        db,
        trade,
        status=TradeStatus.CLOSED,
        exit_price=detail.close_price,
        pnl=detail.realized_pnl,
        close_reason=close_reason,
        closed_at=detail.close_time or datetime.now(timezone.utc),
    )
    emoji = "🟢" if detail.realized_pnl >= 0 else "🔴"
    await notify(
        f"{emoji} Trade #{trade.id} ({trade.side} {trade.instrument}) closed [{close_reason}] "
        f"@ {detail.close_price:.2f} | PnL {detail.realized_pnl:+.2f}"
    )
    return detail.realized_pnl


async def reconcile(db: AsyncSession, broker: BrokerProtocol, mode: str, notify: Notifier = _noop_notifier) -> float:
    """Returns total realized PnL from trades found closed at the broker since last check."""
    broker_positions = await broker.get_open_positions()
    broker_by_id = {p.broker_trade_id: p for p in broker_positions}

    db_open_trades = await crud.get_open_trades(db)
    db_by_broker_id = {t.broker_trade_id: t for t in db_open_trades if t.broker_trade_id}

    total_pnl = 0.0
    for broker_trade_id, trade in db_by_broker_id.items():
        if broker_trade_id not in broker_by_id:
            total_pnl += await _close_from_broker_record(db, broker, trade, notify)

    known_ids = set(db_by_broker_id.keys())
    for broker_trade_id, position in broker_by_id.items():
        if broker_trade_id in known_ids:
            continue
        if position.stop_loss_price is None:
            msg = (
                f"🚨 Found an OPEN position at the broker (trade {broker_trade_id}, {position.side} "
                f"{position.instrument}) with NO stop-loss attached. The bot cannot safely manage this — "
                f"please attach a stop-loss or close it manually in your MT5 terminal."
            )
            logger.error(msg)
            await notify(msg)
            continue
        await crud.create_trade(
            db,
            broker_trade_id=broker_trade_id,
            instrument=position.instrument,
            side=position.side,
            volume=position.volume,
            entry_price=position.entry_price,
            stop_loss_price=position.stop_loss_price,
            take_profit_price=position.take_profit_price,
            trailing_stop_distance=position.trailing_stop_distance,
            status=TradeStatus.OPEN,
            strategy_name="external_reconciled",
            mode=mode,
            opened_at=position.opened_at,
        )
        msg = (
            f"ℹ️ Adopted an untracked open position ({position.side} {position.instrument}, trade "
            f"{broker_trade_id}) found at the broker. It will now be managed by the bot."
        )
        logger.info(msg)
        await notify(msg)

    return total_pnl
