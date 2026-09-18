from datetime import datetime

from pydantic import BaseModel


class Candle(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    complete: bool


class OrderRequest(BaseModel):
    instrument: str
    side: str  # "buy" | "sell"
    volume: float  # lots (MT5 native quantity) — always positive; sign is derived from side
    stop_loss_price: float
    take_profit_price: float | None = None
    trailing_stop_distance: float | None = None


class OrderResult(BaseModel):
    broker_trade_id: str
    instrument: str
    side: str
    volume: float
    fill_price: float
    stop_loss_price: float
    take_profit_price: float | None = None
    trailing_stop_distance: float | None = None
    filled_at: datetime


class SymbolSpecification(BaseModel):
    """Needed to size positions correctly: risk is computed in account-currency terms
    and must be converted to lots via contract_size, then rounded to volume_step and
    clamped to [min_volume, max_volume] — these vary per broker/symbol and must never
    be assumed (e.g. gold's contract size is commonly 100 oz/lot, but not universally).
    """

    contract_size: float
    min_volume: float
    max_volume: float
    volume_step: float


class Position(BaseModel):
    broker_trade_id: str
    instrument: str
    side: str
    volume: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    trailing_stop_distance: float | None = None
    opened_at: datetime


class TradeDetail(BaseModel):
    """Result of looking up a specific trade by ID — works for OPEN or CLOSED trades,
    which is what lets us recover the real close price/PnL after a broker-side
    stop-loss/take-profit fill instead of having to guess.
    """

    broker_trade_id: str
    instrument: str
    state: str  # "OPEN" | "CLOSED" | "CLOSE_WHEN_TRADEABLE"
    side: str
    entry_price: float
    close_price: float | None = None
    realized_pnl: float
    close_time: datetime | None = None


class AccountSummary(BaseModel):
    balance: float
    equity: float  # balance + unrealized pnl (NAV)
    margin_available: float
    open_position_count: int
    currency: str
