"""In-memory broker simulator implementing `BrokerProtocol`, so the backtester replays
bar-by-bar through the exact same `engine.executor` / `engine.position_manager` code
the live loop uses — no separate, potentially-diverging decision logic for backtests.

Fill assumption: orders fill at the *current* (just-closed) bar's price plus a fixed
spread, not the next bar's open. This matches how the live bot actually behaves — it
evaluates a signal immediately after a candle closes and places a market order right
away, so the realistic reference price is that candle's close, not one bar later.
Waiting for the next bar's open would add a full extra bar of artificial lag that the
live system never has.

Stop-loss/take-profit hit detection uses each bar's high/low. If both would be hit on
the same bar, the stop-loss is assumed to fire first — the pessimistic assumption,
deliberately, so a backtest never overstates the strategy's edge.

Position sizes are in lots, converted to P&L via `contract_size` — this MUST match
your real broker's contract size for the symbol (check its symbol specification in
your MT5 terminal) or the backtest's P&L numbers will be wrong even if the trade
timing is right.
"""
from dataclasses import dataclass

import pandas as pd

from app.broker.schemas import AccountSummary, Candle, OrderRequest, OrderResult, Position, SymbolSpecification, TradeDetail


@dataclass
class _SimPosition:
    trade_id: str
    instrument: str
    side: str
    volume: float
    entry_price: float
    stop_loss_price: float
    take_profit_price: float | None
    trailing_stop_distance: float | None
    opened_at: pd.Timestamp


@dataclass
class ClosedSimTrade:
    trade_id: str
    side: str
    volume: float
    entry_price: float
    entry_time: pd.Timestamp
    exit_price: float
    exit_time: pd.Timestamp
    pnl: float
    exit_reason: str  # "sl_hit" | "tp_hit" | "manual" | "strategy_exit"


class BacktestSimulator:
    def __init__(
        self,
        df: pd.DataFrame,
        instrument: str,
        initial_balance: float,
        spread: float = 0.30,
        contract_size: float = 100.0,
        min_volume: float = 0.01,
        max_volume: float = 100.0,
        volume_step: float = 0.01,
    ):
        """`df` must have columns time/open/high/low/close, sorted ascending. `spread`
        is the full bid/ask spread in price units (a retail gold CFD commonly trades a
        few tens of cents wide — 0.30 is a conservative default). `contract_size`
        defaults to 100 (oz per lot), the common convention for XAUUSD, but VERIFY this
        against your actual broker's symbol specification before trusting results.
        """
        self.df = df.reset_index(drop=True)
        self.instrument = instrument
        self.balance = initial_balance
        self.spread = spread
        self.spec = SymbolSpecification(
            contract_size=contract_size, min_volume=min_volume, max_volume=max_volume, volume_step=volume_step
        )
        self._bar_index = 0
        self._next_trade_id = 1
        self._open_positions: dict[str, _SimPosition] = {}
        self.closed_trades: list[ClosedSimTrade] = []

    def advance_to(self, bar_index: int) -> None:
        self._bar_index = bar_index

    @property
    def current_bar(self) -> pd.Series:
        return self.df.iloc[self._bar_index]

    def visible_df(self, lookback: int = 250) -> pd.DataFrame:
        start = max(0, self._bar_index - lookback + 1)
        return self.df.iloc[start : self._bar_index + 1].reset_index(drop=True)

    def process_stop_and_target_hits(self) -> list[ClosedSimTrade]:
        """Checks the current bar's high/low against each open position's stop/target
        and closes any that were breached. Call once per bar, before management logic
        gets a chance to act on stale positions.
        """
        bar = self.current_bar
        closed = []
        for trade_id, pos in list(self._open_positions.items()):
            exit_price = None
            reason = None
            if pos.side == "buy":
                if bar.low <= pos.stop_loss_price:
                    exit_price, reason = pos.stop_loss_price, "sl_hit"
                elif pos.take_profit_price is not None and bar.high >= pos.take_profit_price:
                    exit_price, reason = pos.take_profit_price, "tp_hit"
            else:
                if bar.high >= pos.stop_loss_price:
                    exit_price, reason = pos.stop_loss_price, "sl_hit"
                elif pos.take_profit_price is not None and bar.low <= pos.take_profit_price:
                    exit_price, reason = pos.take_profit_price, "tp_hit"

            if exit_price is not None:
                record = self._close_internal(pos, exit_price, reason, bar.time)
                closed.append(record)
        return closed

    def _pnl(self, side: str, volume: float, entry_price: float, exit_price: float) -> float:
        diff = exit_price - entry_price if side == "buy" else entry_price - exit_price
        return diff * volume * self.spec.contract_size

    def _close_internal(self, pos: _SimPosition, exit_price: float, reason: str, exit_time) -> ClosedSimTrade:
        pnl = self._pnl(pos.side, pos.volume, pos.entry_price, exit_price)
        self.balance += pnl
        del self._open_positions[pos.trade_id]
        record = ClosedSimTrade(
            trade_id=pos.trade_id,
            side=pos.side,
            volume=pos.volume,
            entry_price=pos.entry_price,
            entry_time=pos.opened_at,
            exit_price=exit_price,
            exit_time=exit_time,
            pnl=pnl,
            exit_reason=reason,
        )
        self.closed_trades.append(record)
        return record

    # --- BrokerProtocol implementation ------------------------------------------

    async def get_candles(self, instrument: str, timeframe: str, count: int = 200, start=None) -> list[Candle]:
        window = self.visible_df(lookback=count)
        return [
            Candle(time=row.time, open=row.open, high=row.high, low=row.low, close=row.close, volume=0, complete=True)
            for row in window.itertuples()
        ]

    async def get_symbol_specification(self, instrument: str) -> SymbolSpecification:
        return self.spec

    async def place_order(self, order: OrderRequest) -> OrderResult:
        bar = self.current_bar
        fill_price = bar.close + self.spread / 2 if order.side == "buy" else bar.close - self.spread / 2
        trade_id = str(self._next_trade_id)
        self._next_trade_id += 1
        self._open_positions[trade_id] = _SimPosition(
            trade_id=trade_id,
            instrument=order.instrument,
            side=order.side,
            volume=order.volume,
            entry_price=fill_price,
            stop_loss_price=order.stop_loss_price,
            take_profit_price=order.take_profit_price,
            trailing_stop_distance=order.trailing_stop_distance,
            opened_at=bar.time,
        )
        return OrderResult(
            broker_trade_id=trade_id,
            instrument=order.instrument,
            side=order.side,
            volume=order.volume,
            fill_price=fill_price,
            stop_loss_price=order.stop_loss_price,
            take_profit_price=order.take_profit_price,
            trailing_stop_distance=order.trailing_stop_distance,
            filled_at=bar.time,
        )

    async def get_open_positions(self) -> list[Position]:
        bar = self.current_bar
        positions = []
        for pos in self._open_positions.values():
            unrealized = self._pnl(pos.side, pos.volume, pos.entry_price, bar.close)
            positions.append(
                Position(
                    broker_trade_id=pos.trade_id,
                    instrument=pos.instrument,
                    side=pos.side,
                    volume=pos.volume,
                    entry_price=pos.entry_price,
                    current_price=bar.close,
                    unrealized_pnl=unrealized,
                    stop_loss_price=pos.stop_loss_price,
                    take_profit_price=pos.take_profit_price,
                    trailing_stop_distance=pos.trailing_stop_distance,
                    opened_at=pos.opened_at,
                )
            )
        return positions

    async def modify_stop_loss(self, broker_trade_id: str, new_stop_loss_price: float) -> None:
        if broker_trade_id in self._open_positions:
            self._open_positions[broker_trade_id].stop_loss_price = new_stop_loss_price

    async def close_position(self, broker_trade_id: str) -> float:
        pos = self._open_positions[broker_trade_id]
        bar = self.current_bar
        exit_price = bar.close - self.spread / 2 if pos.side == "buy" else bar.close + self.spread / 2
        record = self._close_internal(pos, exit_price, "manual", bar.time)
        return record.exit_price

    async def get_account_summary(self) -> AccountSummary:
        bar = self.current_bar
        unrealized = sum(self._pnl(p.side, p.volume, p.entry_price, bar.close) for p in self._open_positions.values())
        return AccountSummary(
            balance=self.balance,
            equity=self.balance + unrealized,
            margin_available=self.balance,
            open_position_count=len(self._open_positions),
            currency="USD",
        )

    async def get_trade(self, broker_trade_id: str) -> TradeDetail:
        for record in self.closed_trades:
            if record.trade_id == broker_trade_id:
                return TradeDetail(
                    broker_trade_id=record.trade_id,
                    instrument=self.instrument,
                    state="CLOSED",
                    side=record.side,
                    entry_price=record.entry_price,
                    close_price=record.exit_price,
                    realized_pnl=record.pnl,
                    close_time=record.exit_time,
                )
        pos = self._open_positions[broker_trade_id]
        return TradeDetail(
            broker_trade_id=pos.trade_id,
            instrument=pos.instrument,
            state="OPEN",
            side=pos.side,
            entry_price=pos.entry_price,
            realized_pnl=0.0,
        )

    def close_all_at_market(self, reason: str = "backtest_end") -> list[ClosedSimTrade]:
        bar = self.current_bar
        closed = []
        for pos in list(self._open_positions.values()):
            exit_price = bar.close - self.spread / 2 if pos.side == "buy" else bar.close + self.spread / 2
            closed.append(self._close_internal(pos, exit_price, reason, bar.time))
        return closed
