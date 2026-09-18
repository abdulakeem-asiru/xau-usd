from datetime import datetime
from typing import Protocol

from app.broker.schemas import AccountSummary, Candle, OrderRequest, OrderResult, Position, SymbolSpecification, TradeDetail


class BrokerProtocol(Protocol):
    """Structural interface implemented by both the live MetaApi (MT5) client and the
    backtest simulator, so `app/engine` decision logic runs unmodified against
    either one — no strategy/risk code should ever import metaapi_client directly.
    """

    async def get_candles(
        self, instrument: str, timeframe: str, count: int = 200, start: datetime | None = None
    ) -> list[Candle]: ...

    async def get_symbol_specification(self, instrument: str) -> SymbolSpecification:
        """Contract size / volume constraints for the instrument — required to size
        a position correctly. Never assume a default; always look this up.
        """
        ...

    async def place_order(self, order: OrderRequest) -> OrderResult: ...

    async def get_open_positions(self) -> list[Position]: ...

    async def get_trade(self, broker_trade_id: str) -> TradeDetail:
        """Looks up a trade by ID regardless of whether it's still open or already
        closed — used to recover the real close price/PnL after a broker-side
        stop-loss/take-profit fill.
        """
        ...

    async def modify_stop_loss(self, broker_trade_id: str, new_stop_loss_price: float) -> None: ...

    async def close_position(self, broker_trade_id: str) -> float:
        """Closes the position at market and returns the fill price."""
        ...

    async def get_account_summary(self) -> AccountSummary: ...
