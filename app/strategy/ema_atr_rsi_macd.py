import pandas as pd

from app.broker.schemas import Position
from app.strategy.base import StrategyBase
from app.strategy.indicators import add_indicators, min_bars_required
from app.strategy.signal import Adjustment, Signal


def _recent_cross(hist: pd.Series, direction: str, window: int) -> bool:
    """True if `hist` crossed zero in `direction` ("up"/"down") at any point within
    the last `window` bars. A single-bar-exact check is too brittle: MACD and RSI
    can shift relative to each other by a bar or two even in a clean trend, which
    would otherwise cause entries/exits to be missed entirely.
    """
    tail = hist.iloc[-(window + 1):]
    for i in range(1, len(tail)):
        prev, curr = tail.iloc[i - 1], tail.iloc[i]
        if direction == "up" and prev <= 0 < curr:
            return True
        if direction == "down" and prev >= 0 > curr:
            return True
    return False


class EmaAtrRsiMacdStrategy(StrategyBase):
    """Trend-following + momentum strategy.

    Entry: EMA(fast)/EMA(slow) defines trend direction. A fresh MACD-histogram
    zero-line cross in the trend direction is the entry trigger (not just "MACD
    is positive", which would fire on every bar while conditions hold). RSI
    confirms momentum without chasing an already-extreme move.

    Exit/management (`manage_position`) is a separate, ongoing decision made every
    loop tick — not just the initial stop-loss. It ratchets the stop to breakeven
    and then trails it as the trade moves favorably, and closes early if momentum
    flips against the position before either the stop or a take-profit would fire.
    A stop is never loosened, only tightened — that's a hard invariant, not a tunable.
    """

    name = "ema_atr_rsi_macd"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        p = self.params
        self.ema_fast = int(p.get("ema_fast", 20))
        self.ema_slow = int(p.get("ema_slow", 50))
        self.atr_period = int(p.get("atr_period", 14))
        self.rsi_period = int(p.get("rsi_period", 14))
        self.macd_fast = int(p.get("macd_fast", 12))
        self.macd_slow = int(p.get("macd_slow", 26))
        self.macd_signal = int(p.get("macd_signal", 9))
        self.atr_stop_multiplier = float(p.get("atr_stop_multiplier", 1.5))
        self.take_profit_rr = p.get("take_profit_rr")  # None => no fixed take-profit, rely on management
        self.breakeven_trigger_atr = float(p.get("breakeven_trigger_atr", 1.0))
        self.trail_trigger_atr = float(p.get("trail_trigger_atr", 2.0))
        self.trail_atr_multiplier = float(p.get("trail_atr_multiplier", 1.5))
        # RSI is only used to filter out already-extreme readings, not to require a
        # narrow momentum "sweet spot" — RSI (fast, 14-period) and MACD (slower,
        # 12/26/9) naturally drift out of phase during ordinary pullback cycles, so a
        # tight band combined with a MACD-cross trigger would rarely align in practice.
        self.rsi_buy_min = float(p.get("rsi_buy_min", 40))
        self.rsi_buy_max = float(p.get("rsi_buy_max", 85))
        self.rsi_sell_min = float(p.get("rsi_sell_min", 15))
        self.rsi_sell_max = float(p.get("rsi_sell_max", 60))
        self.momentum_confirm_window = int(p.get("momentum_confirm_window", 3))

    def _with_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return add_indicators(
            df,
            ema_fast=self.ema_fast,
            ema_slow=self.ema_slow,
            atr_period=self.atr_period,
            rsi_period=self.rsi_period,
            macd_fast=self.macd_fast,
            macd_slow=self.macd_slow,
            macd_signal=self.macd_signal,
        )

    def generate_signal(self, df: pd.DataFrame) -> Signal | None:
        min_bars = min_bars_required(self.ema_slow, self.macd_slow, self.macd_signal)
        if len(df) < min_bars:
            return None

        d = self._with_indicators(df)
        latest = d.iloc[-1]
        if latest[["ema_fast", "ema_slow", "atr", "rsi", "macd_hist"]].isna().any():
            return None

        entry_price = float(latest["close"])
        atr = float(latest["atr"])
        macd_cross_up = _recent_cross(d["macd_hist"], "up", self.momentum_confirm_window)
        macd_cross_down = _recent_cross(d["macd_hist"], "down", self.momentum_confirm_window)
        uptrend = latest["ema_fast"] > latest["ema_slow"]
        downtrend = latest["ema_fast"] < latest["ema_slow"]

        reason = {
            "entry_price": entry_price,
            "ema_fast": float(latest["ema_fast"]),
            "ema_slow": float(latest["ema_slow"]),
            "atr": atr,
            "rsi": float(latest["rsi"]),
            "macd_hist": float(latest["macd_hist"]),
        }

        if uptrend and macd_cross_up and self.rsi_buy_min < latest["rsi"] < self.rsi_buy_max:
            stop_loss = entry_price - self.atr_stop_multiplier * atr
            take_profit = entry_price + self.take_profit_rr * (entry_price - stop_loss) if self.take_profit_rr else None
            return Signal(side="buy", stop_loss_price=stop_loss, take_profit_price=take_profit,
                          trailing_stop_distance=None, reason=reason)

        if downtrend and macd_cross_down and self.rsi_sell_min < latest["rsi"] < self.rsi_sell_max:
            stop_loss = entry_price + self.atr_stop_multiplier * atr
            take_profit = entry_price - self.take_profit_rr * (stop_loss - entry_price) if self.take_profit_rr else None
            return Signal(side="sell", stop_loss_price=stop_loss, take_profit_price=take_profit,
                          trailing_stop_distance=None, reason=reason)

        return None

    def manage_position(self, position: Position, df: pd.DataFrame) -> Adjustment:
        min_bars = min_bars_required(self.ema_slow, self.macd_slow, self.macd_signal)
        if len(df) < min_bars:
            return Adjustment(action="hold")

        d = self._with_indicators(df)
        latest = d.iloc[-1]
        if latest[["atr", "rsi", "macd_hist"]].isna().any():
            return Adjustment(action="hold")

        atr = float(latest["atr"])
        current_price = float(latest["close"])
        current_stop = position.stop_loss_price

        if position.side == "buy":
            favorable_move = current_price - position.entry_price
            # Exits react faster than entries on purpose: entries stay selective (trend +
            # fresh MACD cross + RSI not-extreme) to avoid over-trading, but once a position
            # is open the broker-side stop-loss is already the hard backstop, so protecting
            # gains/cutting a reversal on the MACD flip alone — without waiting on RSI to
            # catch up — is the safer default (a missed early exit risks more than a false one).
            momentum_reversed = _recent_cross(d["macd_hist"], "down", self.momentum_confirm_window)

            if momentum_reversed:
                return Adjustment(action="close", reason="momentum reversed against long position")

            candidate_stop = None
            if favorable_move >= self.trail_trigger_atr * atr:
                candidate_stop = current_price - self.trail_atr_multiplier * atr
                trail_reason = f"trailing stop at {self.trail_trigger_atr}x ATR+ favorable move"
            elif favorable_move >= self.breakeven_trigger_atr * atr:
                candidate_stop = position.entry_price
                trail_reason = f"moved to breakeven after {self.breakeven_trigger_atr}x ATR favorable move"

            if candidate_stop is not None and (current_stop is None or candidate_stop > current_stop):
                return Adjustment(action="move_stop", new_stop_loss_price=candidate_stop, reason=trail_reason)

        else:  # sell
            favorable_move = position.entry_price - current_price
            momentum_reversed = _recent_cross(d["macd_hist"], "up", self.momentum_confirm_window)

            if momentum_reversed:
                return Adjustment(action="close", reason="momentum reversed against short position")

            candidate_stop = None
            if favorable_move >= self.trail_trigger_atr * atr:
                candidate_stop = current_price + self.trail_atr_multiplier * atr
                trail_reason = f"trailing stop at {self.trail_trigger_atr}x ATR+ favorable move"
            elif favorable_move >= self.breakeven_trigger_atr * atr:
                candidate_stop = position.entry_price
                trail_reason = f"moved to breakeven after {self.breakeven_trigger_atr}x ATR favorable move"

            if candidate_stop is not None and (current_stop is None or candidate_stop < current_stop):
                return Adjustment(action="move_stop", new_stop_loss_price=candidate_stop, reason=trail_reason)

        return Adjustment(action="hold")
