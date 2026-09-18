"""Honest performance metrics from a backtest run — this is what replaces a claimed
"80% accuracy" with real, reproducible numbers the user can actually trust.
"""
import math

import pandas as pd

from app.backtest.simulator import ClosedSimTrade


def compute_metrics(closed_trades: list[ClosedSimTrade], equity_curve: list[tuple[pd.Timestamp, float]]) -> dict:
    total_trades = len(closed_trades)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "win_rate": None,
            "max_drawdown_pct": None,
            "sharpe_ratio": None,
            "profit_factor": None,
        }

    wins = [t for t in closed_trades if t.pnl > 0]
    losses = [t for t in closed_trades if t.pnl <= 0]
    win_rate = len(wins) / total_trades * 100

    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "sharpe_ratio": _daily_sharpe_ratio(equity_curve),
        "profit_factor": profit_factor,
    }


def _max_drawdown_pct(equity_curve: list[tuple[pd.Timestamp, float]]) -> float | None:
    if not equity_curve:
        return None
    values = [e for _, e in equity_curve]
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak * 100)
    return max_dd


def _daily_sharpe_ratio(equity_curve: list[tuple[pd.Timestamp, float]]) -> float | None:
    """Standard daily-return Sharpe, annualized with the conventional sqrt(252) factor.
    Uses daily closes of the per-bar equity curve so it doesn't depend on the backtest's
    underlying candle granularity (M15, H1, etc all resample to the same daily basis).
    """
    if len(equity_curve) < 3:
        return None
    series = pd.Series(
        [e for _, e in equity_curve], index=pd.DatetimeIndex([t for t, _ in equity_curve])
    )
    daily = series.resample("1D").last().dropna()
    if len(daily) < 3:
        return None
    daily_returns = daily.pct_change().dropna()
    std = daily_returns.std()
    if std == 0 or math.isnan(std):
        return None
    return float(daily_returns.mean() / std * math.sqrt(252))
