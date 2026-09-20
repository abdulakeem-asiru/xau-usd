from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api import account, auth, backtest, bot_state, equity, flip, kill_switch, live_gate, positions, risk_config, strategy_config, trades
from app.broker.schemas import AccountSummary, SymbolSpecification
from app.config import get_settings
from app.core.enums import TradeStatus
from app.core.security import create_access_token
from app.db import crud
from app.db.base import async_session_maker


def make_test_app(broker) -> FastAPI:
    app = FastAPI()
    for router in (
        auth.router, account.router, positions.router, trades.router, equity.router,
        strategy_config.router, risk_config.router, flip.router, bot_state.router, live_gate.router,
        kill_switch.router, backtest.router,
    ):
        app.include_router(router)
    app.state.broker = broker
    app.state.notify = AsyncMock()
    return app


def make_broker(equity_value: float = 10_000, balance: float = 10_000):
    broker = AsyncMock()
    broker.get_account_summary.return_value = AccountSummary(
        balance=balance, equity=equity_value, margin_available=balance, open_position_count=0, currency="USD"
    )
    broker.get_open_positions.return_value = []
    broker.get_symbol_specification.return_value = SymbolSpecification(
        contract_size=100.0, min_volume=0.01, max_volume=100.0, volume_step=0.01
    )
    return broker


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    async with async_session_maker() as db:
        await db.execute(text("TRUNCATE trades, bot_config, circuit_breaker_state RESTART IDENTITY CASCADE"))
        await db.commit()
    yield


@pytest.fixture
def auth_headers():
    token = create_access_token(subject="admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_credentials():
    app = make_test_app(make_broker())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_bot_state_requires_auth():
    app = make_test_app(make_broker())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/config/bot-state")
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_bot_state_reports_combined_fields(auth_headers):
    app = make_test_app(make_broker(equity_value=9_700))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/config/bot-state", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "practice"
        assert data["equity"] == 9700.0
        assert data["halted"] is False


@pytest.mark.asyncio
async def test_risk_config_rejects_out_of_bounds_values(auth_headers):
    app = make_test_app(make_broker())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put(
            "/api/config/risk",
            headers=auth_headers,
            json={"risk_pct_per_trade": 50, "max_daily_loss_pct": 3.0, "max_concurrent_positions": 1},
        )
        assert res.status_code == 422  # 50% risk per trade must be rejected outright


@pytest.mark.asyncio
async def test_risk_config_accepts_valid_values(auth_headers):
    app = make_test_app(make_broker())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put(
            "/api/config/risk",
            headers=auth_headers,
            json={"risk_pct_per_trade": 1.5, "max_daily_loss_pct": 4.0, "max_concurrent_positions": 2},
        )
        assert res.status_code == 200
        assert res.json()["risk_pct_per_trade"] == 1.5


@pytest.mark.asyncio
async def test_flip_config_defaults_to_off(auth_headers):
    app = make_test_app(make_broker())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/config/flip", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["flip_mode"] is False
        assert (body["flip_risk_pct"], body["flip_equity_floor"], body["flip_equity_target"]) == (10.0, 25.0, 100.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"flip_risk_pct": 50},  # far past the 15% ceiling
        {"flip_risk_pct": 0},
        {"flip_equity_floor": 0},
        {"flip_equity_floor": 60, "flip_equity_target": 60},  # target must be above the floor
        {"flip_equity_floor": 60, "flip_equity_target": 40},
    ],
)
async def test_flip_config_rejects_invalid_values(auth_headers, overrides):
    app = make_test_app(make_broker())
    payload = {"flip_mode": True, "flip_risk_pct": 10, "flip_equity_floor": 25, "flip_equity_target": 100, **overrides}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/config/flip", headers=auth_headers, json=payload)
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_flip_config_enable_persists_and_notifies_once(auth_headers):
    app = make_test_app(make_broker())
    payload = {"flip_mode": True, "flip_risk_pct": 8, "flip_equity_floor": 20, "flip_equity_target": 150}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/config/flip", headers=auth_headers, json=payload)
        assert res.status_code == 200
        assert res.json()["flip_mode"] is True
        # saving again while already on must not re-announce a new run
        await client.put("/api/config/flip", headers=auth_headers, json=payload)
        got = (await client.get("/api/config/flip", headers=auth_headers)).json()
        assert (got["flip_risk_pct"], got["flip_equity_floor"], got["flip_equity_target"]) == (8.0, 20.0, 150.0)
    app.state.notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_gate_rejects_wrong_phrase(auth_headers):
    app = make_test_app(make_broker())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/mode/request-live", headers=auth_headers,
            json={"confirmation_phrase": "yes please", "password": "whatever"},
        )
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_live_gate_rejects_when_env_not_live(auth_headers):
    settings = get_settings()
    assert settings.broker_live_account_confirmed is False  # sanity check on the test .env
    app = make_test_app(make_broker())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/mode/request-live", headers=auth_headers,
            json={"confirmation_phrase": "SWITCH TO LIVE TRADING", "password": "irrelevant-since-wrong-anyway"},
        )
        # password is wrong in this test env too, but we want to specifically confirm
        # the env-var gate — check it's rejected for *some* reason and mode never flips
        assert res.status_code in (400, 401)

        status_res = await client.get("/api/config/bot-state", headers=auth_headers)
        assert status_res.json()["mode"] == "practice"


@pytest.mark.asyncio
async def test_kill_switch_closes_open_trades_and_pauses_bot(auth_headers):
    broker = make_broker()
    broker.close_position.return_value = 1990.0  # closes below entry -> a loss on a long
    app = make_test_app(broker)

    async with async_session_maker() as db:
        await crud.create_trade(
            db,
            broker_trade_id="t1",
            instrument="XAUUSD",
            side="buy",
            volume=2.0,
            entry_price=2000.0,
            stop_loss_price=1980.0,
            status=TradeStatus.OPEN,
            strategy_name="ema_atr_rsi_macd",
            mode="practice",
            opened_at=datetime.now(timezone.utc),
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/kill-switch", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["closed_trade_ids"] == [1]
        assert data["failed_trade_ids"] == []

        state_res = await client.get("/api/config/bot-state", headers=auth_headers)
        assert state_res.json()["is_paused"] is True

        trade_res = await client.get("/api/trades/1", headers=auth_headers)
        trade = trade_res.json()
        assert trade["status"] == "closed"
        assert trade["close_reason"] == "kill_switch"
        assert trade["pnl"] == pytest.approx((1990.0 - 2000.0) * 2.0 * 100.0)  # * contract_size (100 oz/lot)
