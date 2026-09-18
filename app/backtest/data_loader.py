"""Paginated historical candle fetch for MetaApi. Its `get_historical_candles` loads
BACKWARDS from a given time (or "now" if omitted), capped at 1000 candles per call —
the opposite direction from OANDA's forward pagination, so we walk from `end`
backwards to `start`, prepending each batch, until we've covered the whole range.
"""
import logging
from datetime import datetime

from app.broker.metaapi_client import MetaApiClient
from app.broker.schemas import Candle

logger = logging.getLogger(__name__)

MAX_CANDLES_PER_REQUEST = 1000


async def load_historical_candles(
    broker: MetaApiClient, instrument: str, timeframe: str, start: datetime, end: datetime
) -> list[Candle]:
    all_candles: list[Candle] = []
    cursor: datetime | None = end

    while True:
        batch = await broker.get_candles(instrument, timeframe, count=MAX_CANDLES_PER_REQUEST, start=cursor)
        if not batch:
            break
        batch = [c for c in batch if c.time >= start]
        all_candles = batch + all_candles
        earliest = batch[0].time
        logger.info("Loaded %d candles back to %s (total so far: %d)", len(batch), earliest, len(all_candles))

        if earliest <= start or len(batch) < MAX_CANDLES_PER_REQUEST:
            break
        cursor = earliest

    return sorted(all_candles, key=lambda c: c.time)
