"""TradingLoop behaviour with flip mode on. DB-backed like tests/test_api.py — point
DATABASE_URL at a throwaway database, since the fixture below truncates tables."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.broker.schemas import AccountSummary, Candle, Position, SymbolSpecification
from app.config import get_settings
from app.core.enums import BotMode
from app.db import crud
from app.db.base import async_session_maker
from app.engine import trading_loop as trading_loop_module
from app.engine.trading_loop import TradingLoop


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    async with async_session_maker() as db:
        await db.execute(
            text("TRUNCATE trades, bot_config, circuit_breaker_state, equity_snapshots RESTART IDENTITY CASCADE")
        )
        await db.commit()
    yield


def _candles(n: int = 80) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2400.0,
            high=2400.6,
            low=2399.4,
            close=2400.0,
            volume=0,
            complete=True,
        )
        for i in range(n)
    ]


def _broker(equity: float, positions: list[Position] | None = None) -> AsyncMock:
    broker = AsyncMock()
    broker.get_account_summary.return_value = AccountSummary(
        balance=equity, equity=equity, margin_available=equity, open_position_count=0, currency="USD"
    )
    broker.get_open_positions.return_value = positions or []
    broker.get_symbol_specification.return_value = SymbolSpecification(
        contract_size=100.0, min_volume=0.01, max_volume=100.0, volume_step=0.01
    )
    broker.get_candles.return_value = _candles()
    return broker


async def _turn_on_flip() -> None:
    async with async_session_maker() as db:
        await crud.update_bot_config(
            db,
            mode=BotMode.LIVE,
            flip_mode=True,
            flip_risk_pct=10.0,
            flip_equity_floor=25.0,
            flip_equity_target=100.0,
        )


@pytest.fixture
def captured_ctx(monkeypatch):
    seen = []

    async def fake_evaluate(df, broker, ctx):
        seen.append(ctx)
        return None

    monkeypatch.setattr(trading_loop_module, "evaluate_and_maybe_trade", fake_evaluate)
    return seen


@pytest.mark.asyncio
async def test_flip_run_ends_and_pauses_when_flat_at_the_floor(captured_ctx):
    await _turn_on_flip()
    notify = AsyncMock()
    loop = TradingLoop(_broker(equity=24.0), get_settings(), notify=notify)

    await loop._tick()

    async with async_session_maker() as db:
        config = await crud.get_bot_config(db)
    assert config.flip_mode is False
    assert config.is_paused is True
    assert captured_ctx == []  # no entry was even considered
    notify.assert_awaited_once()
    assert "floor" in notify.await_args.args[0]


@pytest.mark.asyncio
async def test_flip_run_ends_and_pauses_when_flat_at_the_target(captured_ctx):
    await _turn_on_flip()
    notify = AsyncMock()
    loop = TradingLoop(_broker(equity=101.0), get_settings(), notify=notify)

    await loop._tick()

    async with async_session_maker() as db:
        config = await crud.get_bot_config(db)
    assert config.flip_mode is False
    assert config.is_paused is True
    assert captured_ctx == []
    assert "target" in notify.await_args.args[0]


@pytest.mark.asyncio
async def test_flip_mode_sizes_entries_with_the_flip_risk_while_inside_the_band(captured_ctx):
    await _turn_on_flip()
    loop = TradingLoop(_broker(equity=50.5), get_settings(), notify=AsyncMock())

    await loop._tick()

    async with async_session_maker() as db:
        config = await crud.get_bot_config(db)
    assert config.flip_mode is True
    assert config.is_paused is False
    assert len(captured_ctx) == 1
    assert captured_ctx[0].risk_pct_per_trade == 10.0  # not the normal 1.0


@pytest.mark.asyncio
async def test_normal_risk_is_used_when_flip_mode_is_off(captured_ctx):
    async with async_session_maker() as db:
        await crud.update_bot_config(db, mode=BotMode.LIVE, risk_pct_per_trade=1.0)
    loop = TradingLoop(_broker(equity=50.5), get_settings(), notify=AsyncMock())

    await loop._tick()

    assert len(captured_ctx) == 1
    assert captured_ctx[0].risk_pct_per_trade == 1.0


@pytest.mark.asyncio
async def test_flip_run_is_not_ended_while_a_position_is_open(captured_ctx, monkeypatch):
    # Equity is below the floor, but a position is open: pausing now would stop the tick
    # loop from managing it, so the run must wait until the account is flat.
    async def no_management(positions, df, strategy, broker):
        return []

    monkeypatch.setattr(trading_loop_module, "manage_open_positions", no_management)
    await _turn_on_flip()
    open_position = Position(
        broker_trade_id="123",
        instrument="XAUUSD",
        side="buy",
        volume=0.01,
        entry_price=2400.0,
        current_price=2380.0,
        unrealized_pnl=-20.0,
        stop_loss_price=2375.0,
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    notify = AsyncMock()
    loop = TradingLoop(_broker(equity=24.0, positions=[open_position]), get_settings(), notify=notify)

    await loop._tick()

    async with async_session_maker() as db:
        config = await crud.get_bot_config(db)
    assert config.flip_mode is True
    assert config.is_paused is False
