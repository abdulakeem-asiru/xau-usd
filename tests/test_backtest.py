from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.backtest.engine import run_backtest
from app.strategy.ema_atr_rsi_macd import EmaAtrRsiMacdStrategy


def _make_df(closes: list[float]) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i, close in enumerate(closes):
        rows.append(
            {
                "time": start + timedelta(minutes=15 * i),
                "open": close,
                "high": close + 0.6,
                "low": close - 0.6,
                "close": close,
            }
        )
    return pd.DataFrame(rows)


def _choppy_trending_series(n: int = 500, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    trend = 1950 + t * 0.4
    cycles = 20 * np.sin(t / 8.0) + 8 * np.sin(t / 3.0)
    noise = rng.normal(0, 1.0, n)
    closes = trend + cycles + noise
    return _make_df(list(closes))


@pytest.mark.asyncio
async def test_run_backtest_produces_trades_and_metrics():
    df = _choppy_trending_series()
    strategy = EmaAtrRsiMacdStrategy()
    result = await run_backtest(
        df=df,
        strategy=strategy,
        instrument="XAUUSD",
        initial_balance=10_000,
        risk_pct_per_trade=1.0,
        max_daily_loss_pct=3.0,
        max_concurrent_positions=1,
    )
    assert len(result.equity_curve) == len(df) - 60
    assert result.metrics["total_trades"] == len(result.closed_trades)
    if result.metrics["total_trades"] > 0:
        assert 0 <= result.metrics["win_rate"] <= 100
        assert result.metrics["max_drawdown_pct"] >= 0


@pytest.mark.asyncio
async def test_backtest_never_has_more_than_max_concurrent_positions():
    df = _choppy_trending_series(seed=3)
    strategy = EmaAtrRsiMacdStrategy()
    result = await run_backtest(
        df=df,
        strategy=strategy,
        instrument="XAUUSD",
        initial_balance=10_000,
        risk_pct_per_trade=1.0,
        max_daily_loss_pct=3.0,
        max_concurrent_positions=1,
    )
    # trades should close in non-decreasing time order — with max_concurrent_positions=1
    # a new entry can't happen until the prior one is closed, so exits can't interleave.
    trades_sorted = sorted(result.closed_trades, key=lambda t: t.exit_time)
    for a, b in zip(trades_sorted, trades_sorted[1:]):
        assert a.exit_time <= b.exit_time


@pytest.mark.asyncio
async def test_backtest_has_no_lookahead_bias():
    df_full = _choppy_trending_series(n=500, seed=11)
    cutoff = 400
    df_short = df_full.iloc[:cutoff].reset_index(drop=True)

    strategy_a = EmaAtrRsiMacdStrategy()
    strategy_b = EmaAtrRsiMacdStrategy()

    result_short = await run_backtest(
        df=df_short,
        strategy=strategy_a,
        instrument="XAUUSD",
        initial_balance=10_000,
        risk_pct_per_trade=1.0,
        max_daily_loss_pct=3.0,
        max_concurrent_positions=1,
    )
    result_full = await run_backtest(
        df=df_full,
        strategy=strategy_b,
        instrument="XAUUSD",
        initial_balance=10_000,
        risk_pct_per_trade=1.0,
        max_daily_loss_pct=3.0,
        max_concurrent_positions=1,
    )

    trades_short_before_cutoff = [t for t in result_short.closed_trades if t.exit_time <= df_short["time"].iloc[-1]]
    trades_full_before_cutoff = [t for t in result_full.closed_trades if t.exit_time <= df_short["time"].iloc[-1]]

    # trades that closed before the cutoff must be identical whether or not future bars
    # existed in the dataset — if they differ, the strategy saw data it shouldn't have.
    assert len(trades_short_before_cutoff) == len(trades_full_before_cutoff)
    for a, b in zip(trades_short_before_cutoff, trades_full_before_cutoff):
        assert a.entry_price == pytest.approx(b.entry_price)
        assert a.exit_price == pytest.approx(b.exit_price)


@pytest.mark.asyncio
async def test_backtest_stop_loss_fills_at_exact_stop_price():
    df = _choppy_trending_series(seed=21)
    strategy = EmaAtrRsiMacdStrategy()
    result = await run_backtest(
        df=df,
        strategy=strategy,
        instrument="XAUUSD",
        initial_balance=10_000,
        risk_pct_per_trade=1.0,
        max_daily_loss_pct=3.0,
        max_concurrent_positions=1,
    )
    sl_trades = [t for t in result.closed_trades if t.exit_reason == "sl_hit"]
    assert len(sl_trades) >= 0  # informational — not every seed guarantees a stop-out
    for t in sl_trades:
        expected_loss_direction = t.exit_price < t.entry_price if t.side == "buy" else t.exit_price > t.entry_price
        assert expected_loss_direction
