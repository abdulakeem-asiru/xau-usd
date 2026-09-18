"""Async client wrapping the official MetaApi Python SDK, bridging this bot to your
MT5 broker account. MetaApi is used (rather than a hand-rolled MT5 REST client)
because it's the standard, actively-maintained way to get programmatic access to an
MT5 account — MT5 itself has no native REST/WebSocket API.

All field names and method signatures here were verified directly against the
installed `metaapi_cloud_sdk` package source (not guessed from documentation), since
this handles real trades.
"""
import logging
from datetime import datetime, timezone

from metaapi_cloud_sdk import MetaApi
from metaapi_cloud_sdk.clients.metaapi.trade_exception import TradeException

from app.broker.schemas import (
    AccountSummary,
    Candle,
    OrderRequest,
    OrderResult,
    Position,
    SymbolSpecification,
    TradeDetail,
)
from app.config import Settings

logger = logging.getLogger(__name__)

_CLOSING_ENTRY_TYPES = {"DEAL_ENTRY_OUT", "DEAL_ENTRY_OUT_BY"}


class MetaApiError(RuntimeError):
    pass


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class MetaApiClient:
    """Implements `app.broker.interface.BrokerProtocol` against a MetaApi-bridged MT5
    account. Unlike OANDA's stateless REST calls, MetaApi requires an explicit
    connect/deploy/synchronize lifecycle — call `connect()` once at startup and
    `aclose()` once at shutdown; every other method assumes `connect()` has completed.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._api = MetaApi(settings.metaapi_token, {"domain": settings.metaapi_domain})
        self._account = None
        self._connection = None

    async def connect(self) -> None:
        self._account = await self._api.metatrader_account_api.get_account(self._settings.metaapi_account_id)
        if self._account.state != "DEPLOYED":
            logger.info("Deploying MetaApi account %s...", self._settings.metaapi_account_id)
            await self._account.deploy()
        logger.info("Waiting for MetaApi to connect to the broker (can take a couple of minutes)...")
        await self._account.wait_connected()
        self._connection = self._account.get_rpc_connection()
        await self._connection.connect()
        logger.info("Waiting for terminal state synchronization...")
        await self._connection.wait_synchronized()
        logger.info("MetaApi connection ready.")

    async def aclose(self) -> None:
        if self._connection is not None:
            await self._connection.close()

    async def get_candles(
        self, instrument: str, timeframe: str, count: int = 200, start: datetime | None = None
    ) -> list[Candle]:
        # get_historical_candles loads BACKWARDS from start_time (latest-first), the
        # opposite direction from OANDA's forward pagination — data_loader.py accounts
        # for this when walking a long historical range.
        raw = await self._account.get_historical_candles(instrument, timeframe, start, min(count, 1000))
        candles = [
            Candle(
                time=_as_utc(c["time"]),
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                volume=int(c.get("tickVolume") or c.get("volume") or 0),
                complete=True,
            )
            for c in raw
        ]
        return sorted(candles, key=lambda c: c.time)

    async def get_symbol_specification(self, instrument: str) -> SymbolSpecification:
        spec = await self._connection.get_symbol_specification(instrument)
        return SymbolSpecification(
            contract_size=spec["contractSize"],
            min_volume=spec["minVolume"],
            max_volume=spec["maxVolume"],
            volume_step=spec["volumeStep"],
        )

    async def place_order(self, order: OrderRequest) -> OrderResult:
        try:
            if order.side == "buy":
                response = await self._connection.create_market_buy_order(
                    order.instrument, order.volume, stop_loss=order.stop_loss_price, take_profit=order.take_profit_price
                )
            else:
                response = await self._connection.create_market_sell_order(
                    order.instrument, order.volume, stop_loss=order.stop_loss_price, take_profit=order.take_profit_price
                )
        except TradeException as exc:
            raise MetaApiError(f"Order failed [{exc.stringCode}]: {exc}") from exc

        position_id = response["positionId"]
        if not position_id:
            raise MetaApiError(f"Order response had no positionId — cannot confirm the trade opened: {response}")
        position = await self._connection.get_position(position_id)

        return OrderResult(
            broker_trade_id=str(position_id),
            instrument=order.instrument,
            side=order.side,
            volume=order.volume,
            fill_price=position["openPrice"],
            stop_loss_price=order.stop_loss_price,
            take_profit_price=order.take_profit_price,
            trailing_stop_distance=order.trailing_stop_distance,
            filled_at=_as_utc(position["time"]),
        )

    async def get_open_positions(self) -> list[Position]:
        positions = await self._connection.get_positions()
        return [
            Position(
                broker_trade_id=str(p["id"]),
                instrument=p["symbol"],
                side="buy" if p["type"] == "POSITION_TYPE_BUY" else "sell",
                volume=p["volume"],
                entry_price=p["openPrice"],
                current_price=p["currentPrice"],
                unrealized_pnl=p["profit"],
                stop_loss_price=p.get("stopLoss"),
                take_profit_price=p.get("takeProfit"),
                opened_at=_as_utc(p["time"]),
            )
            for p in positions
        ]

    async def modify_stop_loss(self, broker_trade_id: str, new_stop_loss_price: float) -> None:
        try:
            await self._connection.modify_position(broker_trade_id, stop_loss=new_stop_loss_price)
        except TradeException as exc:
            raise MetaApiError(f"Modify stop-loss failed [{exc.stringCode}]: {exc}") from exc

    async def close_position(self, broker_trade_id: str) -> float:
        try:
            await self._connection.close_position(broker_trade_id)
        except TradeException as exc:
            raise MetaApiError(f"Close position failed [{exc.stringCode}]: {exc}") from exc
        # The close response has no fill price (verified against MetatraderTradeResponse) —
        # recover it from the position's deal history instead.
        detail = await self.get_trade(broker_trade_id)
        if detail.close_price is None:
            raise MetaApiError(f"Closed position {broker_trade_id} but could not determine its fill price")
        return detail.close_price

    async def get_account_summary(self) -> AccountSummary:
        info = await self._connection.get_account_information()
        positions = await self._connection.get_positions()
        return AccountSummary(
            balance=info["balance"],
            equity=info["equity"],
            margin_available=info["freeMargin"],
            open_position_count=len(positions),
            currency=info["currency"],
        )

    async def get_trade(self, broker_trade_id: str) -> TradeDetail:
        result = await self._connection.get_deals_by_position(broker_trade_id)
        deals = result["deals"]
        if not deals:
            raise MetaApiError(f"No deal history found for position {broker_trade_id}")

        opening = deals[0]
        closing_deals = [d for d in deals if d.get("entryType") in _CLOSING_ENTRY_TYPES]

        if not closing_deals:
            return TradeDetail(
                broker_trade_id=broker_trade_id,
                instrument=opening.get("symbol", ""),
                state="OPEN",
                side="buy" if opening["type"] == "DEAL_TYPE_BUY" else "sell",
                entry_price=opening.get("price", 0.0),
                realized_pnl=0.0,
            )

        realized_pnl = sum(d.get("profit", 0.0) + d.get("commission", 0.0) + d.get("swap", 0.0) for d in closing_deals)
        last_close = closing_deals[-1]
        return TradeDetail(
            broker_trade_id=broker_trade_id,
            instrument=opening.get("symbol", ""),
            state="CLOSED",
            side="buy" if opening["type"] == "DEAL_TYPE_BUY" else "sell",
            entry_price=opening.get("price", 0.0),
            close_price=last_close.get("price"),
            realized_pnl=realized_pnl,
            close_time=_as_utc(last_close["time"]) if last_close.get("time") else None,
        )
