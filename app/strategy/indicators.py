import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange


def add_indicators(
    df: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
    atr_period: int = 14,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> pd.DataFrame:
    """Appends indicator columns to a candle DataFrame (expects open/high/low/close columns).

    Returns a copy — callers should not assume the input frame is mutated.
    """
    df = df.copy()
    df["ema_fast"] = EMAIndicator(df["close"], window=ema_fast).ema_indicator()
    df["ema_slow"] = EMAIndicator(df["close"], window=ema_slow).ema_indicator()
    df["atr"] = AverageTrueRange(df["high"], df["low"], df["close"], window=atr_period).average_true_range()
    df["rsi"] = RSIIndicator(df["close"], window=rsi_period).rsi()
    macd = MACD(df["close"], window_slow=macd_slow, window_fast=macd_fast, window_sign=macd_signal)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()
    return df


def min_bars_required(ema_slow: int = 50, macd_slow: int = 26, macd_signal: int = 9) -> int:
    """Minimum candle count needed before indicators stop producing NaN, plus a safety buffer."""
    return max(ema_slow, macd_slow + macd_signal) + 10
