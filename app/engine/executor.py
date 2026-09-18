"""Entry-decision logic shared verbatim by the live trading loop and the backtester.

Deliberately has zero DB dependency — persistence differs completely between live
(writes to the `trades` table) and backtest (writes to `backtest_trades`), so the
caller owns persistence. This function only decides whether to trade and, if so,
places the order through whichever BrokerProtocol implementation it's given.
"""
import logging
from dataclasses import dataclass

import pandas as pd

from app.broker.interface import BrokerProtocol
from app.broker.schemas import OrderRequest, OrderResult
from app.risk import limits, position_sizing
from app.risk.circuit_breaker import CircuitBreaker, CircuitBreakerSnapshot
from app.risk.position_sizing import PositionTooSmallError
from app.strategy.base import StrategyBase
from app.strategy.signal import Signal

logger = logging.getLogger(__name__)


@dataclass
class RunContext:
    strategy: StrategyBase
    circuit_breaker: CircuitBreaker
    breaker_snapshot: CircuitBreakerSnapshot
    risk_pct_per_trade: float
    max_concurrent_positions: int
    open_positions_count: int
    instrument: str


@dataclass
class ExecutionResult:
    order: OrderResult
    signal: Signal
    risk_amount: float


async def evaluate_and_maybe_trade(df: pd.DataFrame, broker: BrokerProtocol, ctx: RunContext) -> ExecutionResult | None:
    if ctx.circuit_breaker.is_halted(ctx.breaker_snapshot):
        return None
    if not limits.can_open_new_position(ctx.open_positions_count, ctx.max_concurrent_positions):
        return None

    signal = ctx.strategy.generate_signal(df)
    if signal is None:
        return None

    account = await broker.get_account_summary()
    spec = await broker.get_symbol_specification(ctx.instrument)
    entry_price = float(df["close"].iloc[-1])
    try:
        volume = position_sizing.size_position(
            equity=account.equity,
            risk_pct_per_trade=ctx.risk_pct_per_trade,
            entry_price=entry_price,
            stop_loss_price=signal.stop_loss_price,
            spec=spec,
        )
    except PositionTooSmallError as exc:
        logger.warning("Skipping signal — %s", exc)
        return None
    risk_amount = account.equity * (ctx.risk_pct_per_trade / 100)

    order = OrderRequest(
        instrument=ctx.instrument,
        side=signal.side,
        volume=volume,
        stop_loss_price=signal.stop_loss_price,
        take_profit_price=signal.take_profit_price,
        trailing_stop_distance=signal.trailing_stop_distance,
    )
    order_result = await broker.place_order(order)
    return ExecutionResult(order=order_result, signal=signal, risk_amount=risk_amount)
