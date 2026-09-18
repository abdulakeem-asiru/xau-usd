import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd

from app.broker.interface import BrokerProtocol
from app.broker.schemas import Candle
from app.config import Settings
from app.core.enums import CloseReason, TradeStatus
from app.db import crud
from app.db.base import async_session_maker
from app.engine import state
from app.engine.executor import RunContext, evaluate_and_maybe_trade
from app.engine.position_manager import manage_open_positions
from app.engine.state import Notifier
from app.risk.circuit_breaker import CircuitBreaker, CircuitBreakerSnapshot
from app.strategy.registry import get_strategy

logger = logging.getLogger(__name__)

MIN_CANDLES_FOR_STRATEGY = 60


def _candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    rows = [{"time": c.time, "open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in candles]
    df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    return df


def _position_pnl(side: str, volume: float, contract_size: float, entry_price: float, exit_price: float) -> float:
    diff = exit_price - entry_price if side == "buy" else entry_price - exit_price
    return diff * volume * contract_size


class TradingLoop:
    """The live asyncio loop: reconcile -> manage open positions -> consider a new
    entry -> persist state -> notify. Runs as a background task started/stopped from
    FastAPI's lifespan. Never lets a single bad iteration kill the process — an
    exception is logged and alerted, and the loop continues on the next tick.
    """

    def __init__(self, broker: BrokerProtocol, settings: Settings, notify: Notifier = state.noop_notifier):
        self.broker = broker
        self.settings = settings
        self.notify = notify
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        async with async_session_maker() as db:
            config = await crud.get_bot_config(db)
            await state.reconcile(db, self.broker, config.mode, self.notify)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="trading_loop")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("Trading loop iteration failed")
                await self.notify("⚠️ Trading loop hit an unexpected error this tick — see logs. Continuing.")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        async with async_session_maker() as db:
            config = await crud.get_bot_config(db)
            if not config.is_running or config.is_paused:
                return

            broker_pnl = await state.reconcile(db, self.broker, config.mode, self.notify)

            account = await self.broker.get_account_summary()
            now = datetime.now(timezone.utc)
            breaker = CircuitBreaker(max_daily_loss_pct=float(config.max_daily_loss_pct))

            db_breaker_row = await crud.get_or_create_todays_circuit_breaker(db, account.equity)
            snapshot = CircuitBreakerSnapshot(
                trading_day=db_breaker_row.trading_day,
                starting_equity=float(db_breaker_row.starting_equity),
                realized_pnl_today=float(db_breaker_row.realized_pnl_today),
                halted=db_breaker_row.halted,
                halted_reason=db_breaker_row.halted_reason,
            )
            if breaker.is_new_trading_day(snapshot, now):
                db_breaker_row = await crud.get_or_create_todays_circuit_breaker(db, account.equity)
                snapshot = breaker.start_new_day(now, account.equity)

            if broker_pnl != 0.0:
                breaker.record_pnl(snapshot, broker_pnl)
                if snapshot.halted and not db_breaker_row.halted:
                    await self.notify(f"🛑 {snapshot.halted_reason} — new entries halted for the rest of the day.")

            spec = await self.broker.get_symbol_specification(self.settings.instrument)
            positions = await self.broker.get_open_positions()
            candles = await self.broker.get_candles(
                self.settings.instrument, self.settings.candle_timeframe, count=250
            )
            complete = [c for c in candles if c.complete]
            if len(complete) < MIN_CANDLES_FOR_STRATEGY:
                logger.info("Not enough complete candles yet (%d) — skipping tick", len(complete))
                return
            df = _candles_to_df(complete)

            strategy = get_strategy(config.strategy_name, config.strategy_params)

            outcomes = await manage_open_positions(positions, df, strategy, self.broker)
            for outcome in outcomes:
                trade = await crud.get_trade_by_broker_id(db, outcome.position.broker_trade_id)
                if trade is None:
                    continue
                if outcome.action == "move_stop":
                    await crud.update_trade(db, trade, stop_loss_price=outcome.new_stop_loss_price)
                    await self.notify(
                        f"🔧 Trade #{trade.id} ({trade.side} {trade.instrument}) stop moved to "
                        f"{outcome.new_stop_loss_price:.2f} — {outcome.reason}"
                    )
                elif outcome.action == "close":
                    pnl = _position_pnl(
                        trade.side, float(trade.volume), spec.contract_size, float(trade.entry_price),
                        outcome.close_fill_price,
                    )
                    await crud.update_trade(
                        db,
                        trade,
                        status=TradeStatus.CLOSED,
                        exit_price=outcome.close_fill_price,
                        pnl=pnl,
                        close_reason=CloseReason.STRATEGY_EXIT,
                        closed_at=now,
                    )
                    breaker.record_pnl(snapshot, pnl)
                    emoji = "🟢" if pnl >= 0 else "🔴"
                    await self.notify(
                        f"{emoji} Trade #{trade.id} ({trade.side} {trade.instrument}) closed early "
                        f"[strategy exit: {outcome.reason}] @ {outcome.close_fill_price:.2f} | PnL {pnl:+.2f}"
                    )

            if any(o.action == "close" for o in outcomes):
                positions = await self.broker.get_open_positions()

            ctx = RunContext(
                strategy=strategy,
                circuit_breaker=breaker,
                breaker_snapshot=snapshot,
                risk_pct_per_trade=float(config.risk_pct_per_trade),
                max_concurrent_positions=config.max_concurrent_positions,
                open_positions_count=len(positions),
                instrument=self.settings.instrument,
            )
            result = await evaluate_and_maybe_trade(df, self.broker, ctx)
            if result is not None:
                await crud.create_trade(
                    db,
                    broker_trade_id=result.order.broker_trade_id,
                    instrument=result.order.instrument,
                    side=result.order.side,
                    volume=result.order.volume,
                    entry_price=result.order.fill_price,
                    stop_loss_price=result.order.stop_loss_price,
                    take_profit_price=result.order.take_profit_price,
                    trailing_stop_distance=result.order.trailing_stop_distance,
                    status=TradeStatus.OPEN,
                    strategy_name=strategy.name,
                    signal_reason=result.signal.reason,
                    risk_amount=result.risk_amount,
                    mode=config.mode,
                    opened_at=result.order.filled_at,
                )
                await self.notify(
                    f"🟢 Opened {result.order.side.upper()} {result.order.volume:.2f} lots "
                    f"{result.order.instrument} @ {result.order.fill_price:.2f} | "
                    f"SL {result.order.stop_loss_price:.2f} | mode={config.mode}"
                )
                positions = await self.broker.get_open_positions()

            await crud.update_circuit_breaker(
                db,
                db_breaker_row,
                realized_pnl_today=snapshot.realized_pnl_today,
                halted=snapshot.halted,
                halted_reason=snapshot.halted_reason,
                halted_at=now if snapshot.halted and not db_breaker_row.halted_at else db_breaker_row.halted_at,
            )
            await crud.add_equity_snapshot(db, account.balance, account.equity, len(positions), config.mode)
