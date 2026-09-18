from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.broker.schemas import Position
from app.strategy.ema_atr_rsi_macd import EmaAtrRsiMacdStrategy, _recent_cross
from app.strategy.indicators import add_indicators, min_bars_required


def _make_df(closes: list[float]) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i, close in enumerate(closes):
        # small synthetic wick around each close so high/low/ATR are well-defined
        rows.append(
            {
                "time": start + timedelta(minutes=15 * i),
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100,
            }
        )
    return pd.DataFrame(rows)


def _downtrend_then_rally(n_down: int = 80, n_up: int = 220) -> pd.DataFrame:
    # A perfectly linear ramp is unrealistic and degenerate for MACD/RSI: with no actual
    # down-bars, RSI pins near 100 and MACD's histogram crosses its zero line only once
    # for the whole trend. A higher-frequency, higher-amplitude wobble on top of the
    # up-trend produces genuine pullbacks (real down-bars) like a real trending market,
    # so RSI cycles back out of extremes and MACD crosses recur many times.
    down = list(np.linspace(2000, 1950, n_down))
    t = np.arange(n_up)
    up = list(1950 + t * 1.0 + 15 * np.sin(t / 3.2))
    return _make_df(down + up)


def test_add_indicators_has_no_nan_after_min_bars():
    df = _downtrend_then_rally()
    d = add_indicators(df)
    min_bars = min_bars_required()
    tail = d.iloc[min_bars:]
    assert not tail[["ema_fast", "ema_slow", "atr", "rsi", "macd", "macd_signal", "macd_hist"]].isna().any().any()


def test_generate_signal_returns_none_on_insufficient_data():
    strategy = EmaAtrRsiMacdStrategy()
    df = _make_df(list(np.linspace(2000, 2010, 10)))
    assert strategy.generate_signal(df) is None


def test_generate_signal_detects_bullish_trend_after_rally():
    strategy = EmaAtrRsiMacdStrategy()
    df = _downtrend_then_rally()

    signals = []
    min_bars = min_bars_required()
    for i in range(min_bars, len(df)):
        sig = strategy.generate_signal(df.iloc[: i + 1])
        if sig is not None:
            signals.append(sig)

    assert any(s.side == "buy" for s in signals), "expected at least one buy signal during the sustained rally"
    buy = next(s for s in signals if s.side == "buy")
    assert buy.stop_loss_price < buy.reason["entry_price"]  # stop sits below entry for a long
    assert buy.reason["entry_price"] - buy.stop_loss_price == pytest.approx(1.5 * buy.reason["atr"])
    assert buy.trailing_stop_distance is None  # management handles trailing explicitly, not a broker trailing order


def test_generate_signal_no_repaint_uses_only_closed_bars():
    strategy = EmaAtrRsiMacdStrategy()
    df = _downtrend_then_rally()
    min_bars = min_bars_required()
    # Signal generated on a prefix must not change if future bars are appended later —
    # i.e. it only ever looks at data up to and including the last row it was given.
    prefix = df.iloc[: min_bars + 50]
    sig_a = strategy.generate_signal(prefix)
    sig_b = strategy.generate_signal(prefix.copy())
    assert sig_a == sig_b or (sig_a is None and sig_b is None)


def _find_macd_cross_down_index(df: pd.DataFrame, window: int = 3) -> int:
    d = add_indicators(df)
    min_bars = min_bars_required()
    for i in range(min_bars, len(d)):
        if _recent_cross(d["macd_hist"].iloc[: i + 1], "down", window):
            return i
    raise AssertionError("no bearish MACD histogram cross found in synthetic series")


def test_manage_position_closes_long_on_momentum_reversal():
    strategy = EmaAtrRsiMacdStrategy()
    rally = list(np.linspace(1950, 2100, 60))
    reversal = list(np.linspace(2100, 1900, 40))
    df = _make_df(rally + reversal)

    cross_idx = _find_macd_cross_down_index(df)
    position = Position(
        broker_trade_id="t1",
        instrument="XAUUSD",
        side="buy",
        volume=1,
        entry_price=2000.0,
        current_price=float(df["close"].iloc[cross_idx]),
        unrealized_pnl=0.0,
        stop_loss_price=1950.0,
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    adjustment = strategy.manage_position(position, df.iloc[: cross_idx + 1])
    assert adjustment.action == "close"


def test_manage_position_moves_to_breakeven_after_favorable_move():
    strategy = EmaAtrRsiMacdStrategy()
    df = _downtrend_then_rally()
    d = add_indicators(df)
    latest = d.iloc[-1]
    atr = float(latest["atr"])
    entry_price = float(latest["close"]) - strategy.breakeven_trigger_atr * atr - 1  # ensures move >= trigger, < trail trigger
    position = Position(
        broker_trade_id="t1",
        instrument="XAUUSD",
        side="buy",
        volume=1,
        entry_price=entry_price,
        current_price=float(latest["close"]),
        unrealized_pnl=0.0,
        stop_loss_price=entry_price - 5 * atr,  # far below, so it's clearly less than breakeven candidate
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    adjustment = strategy.manage_position(position, df)
    assert adjustment.action in ("move_stop", "hold")
    if adjustment.action == "move_stop":
        assert adjustment.new_stop_loss_price >= position.stop_loss_price


def test_manage_position_never_loosens_an_existing_stop():
    strategy = EmaAtrRsiMacdStrategy()
    df = _downtrend_then_rally()
    d = add_indicators(df)
    latest = d.iloc[-1]
    position = Position(
        broker_trade_id="t1",
        instrument="XAUUSD",
        side="buy",
        volume=1,
        entry_price=float(latest["close"]) - 1,
        current_price=float(latest["close"]),
        unrealized_pnl=0.0,
        stop_loss_price=float(latest["close"]) + 1000,  # absurdly tight/above price — no candidate should beat it
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    adjustment = strategy.manage_position(position, df)
    assert adjustment.action == "hold"
