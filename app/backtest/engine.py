"""Bar-by-bar backtest replay. Walks the SAME `engine.executor.evaluate_and_maybe_trade`
and `engine.position_manager.manage_open_positions` code the live loop uses, against
`BacktestSimulator` instead of the real MetaApi client — so a backtest result is a
faithful preview of what the live strategy logic would actually do, not a separate
approximation of it.

No lookahead: `simulator.visible_df()` only ever returns bars up to and including the
current replay index, so the strategy can never see future data it wouldn't have had
live.
"""
from dataclasses import dataclass

import pandas as pd

from app.backtest.metrics import compute_metrics
from app.backtest.simulator import BacktestSimulator, ClosedSimTrade
from app.engine.executor import RunContext, evaluate_and_maybe_trade
from app.engine.position_manager import manage_open_positions
from app.risk.circuit_breaker import CircuitBreaker, CircuitBreakerSnapshot
from app.strategy.base import StrategyBase

MIN_BARS_TO_START = 60
LOOKBACK_BARS = 250


@dataclass
class BacktestResult:
    final_balance: float
    closed_trades: list[ClosedSimTrade]
    equity_curve: list[tuple[pd.Timestamp, float]]
    metrics: dict


async def run_backtest(
    df: pd.DataFrame,
    strategy: StrategyBase,
    instrument: str,
    initial_balance: float,
    risk_pct_per_trade: float,
    max_daily_loss_pct: float,
    max_concurrent_positions: int,
    spread: float = 0.30,
    contract_size: float = 100.0,
    min_volume: float = 0.01,
    max_volume: float = 100.0,
    volume_step: float = 0.01,
) -> BacktestResult:
    if len(df) <= MIN_BARS_TO_START:
        raise ValueError(f"Need more than {MIN_BARS_TO_START} candles to backtest, got {len(df)}")

    simulator = BacktestSimulator(
        df=df,
        instrument=instrument,
        initial_balance=initial_balance,
        spread=spread,
        contract_size=contract_size,
        min_volume=min_volume,
        max_volume=max_volume,
        volume_step=volume_step,
    )
    breaker = CircuitBreaker(max_daily_loss_pct=max_daily_loss_pct)
    snapshot: CircuitBreakerSnapshot | None = None
    equity_curve: list[tuple[pd.Timestamp, float]] = []

    for i in range(MIN_BARS_TO_START, len(df)):
        simulator.advance_to(i)
        bar_time = df["time"].iloc[i]

        account = await simulator.get_account_summary()
        if snapshot is None or breaker.is_new_trading_day(snapshot, bar_time):
            snapshot = breaker.start_new_day(bar_time, account.equity)

        for closed in simulator.process_stop_and_target_hits():
            breaker.record_pnl(snapshot, closed.pnl)

        df_slice = simulator.visible_df(lookback=LOOKBACK_BARS)

        positions = await simulator.get_open_positions()
        outcomes = await manage_open_positions(positions, df_slice, strategy, simulator)
        for outcome in outcomes:
            if outcome.action == "close":
                closed_record = next(
                    t for t in simulator.closed_trades if t.trade_id == outcome.position.broker_trade_id
                )
                breaker.record_pnl(snapshot, closed_record.pnl)

        positions = await simulator.get_open_positions()
        ctx = RunContext(
            strategy=strategy,
            circuit_breaker=breaker,
            breaker_snapshot=snapshot,
            risk_pct_per_trade=risk_pct_per_trade,
            max_concurrent_positions=max_concurrent_positions,
            open_positions_count=len(positions),
            instrument=instrument,
        )
        await evaluate_and_maybe_trade(df_slice, simulator, ctx)

        account = await simulator.get_account_summary()
        equity_curve.append((bar_time, account.equity))

    simulator.close_all_at_market(reason="backtest_end")

    return BacktestResult(
        final_balance=simulator.balance,
        closed_trades=simulator.closed_trades,
        equity_curve=equity_curve,
        metrics=compute_metrics(simulator.closed_trades, equity_curve),
    )
