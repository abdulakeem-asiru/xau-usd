import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import (
    account,
    auth,
    backtest,
    bot_state,
    equity,
    kill_switch,
    live_gate,
    positions,
    risk_config,
    strategy_config,
    trades,
)
from app.broker.metaapi_client import MetaApiClient
from app.config import get_settings
from app.core.logging import setup_logging
from app.engine.trading_loop import TradingLoop
from app.telegram_bot.bot import build_application, setup_webhook
from app.telegram_bot.notifier import TelegramNotifier
from app.telegram_webhook import register_webhook_route
from app.web import routes as web_routes

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    broker = MetaApiClient(settings)
    await broker.connect()
    app.state.broker = broker

    telegram_app = build_application(settings, broker)
    await telegram_app.initialize()
    await telegram_app.start()
    notifier = TelegramNotifier(telegram_app.bot, settings.owner_telegram_chat_id)
    app.state.notify = notifier.send

    try:
        await setup_webhook(telegram_app, settings)
    except Exception:
        logger.exception("Failed to set Telegram webhook — notifications/commands may not work until it's set")

    telegram_router = APIRouter()
    register_webhook_route(telegram_router, telegram_app, settings.telegram_webhook_secret)
    app.include_router(telegram_router)

    trading_loop = TradingLoop(broker, settings, notify=notifier.send)
    app.state.trading_loop = trading_loop
    try:
        await trading_loop.start()
    except Exception:
        logger.exception("Failed to start trading loop on startup")
        await notifier.send("🚨 Trading loop failed to start on boot — check Railway logs immediately.")

    logger.info("Startup complete — mode gate defaults to practice unless already switched to live in bot_config.")

    yield

    await trading_loop.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    await broker.aclose()


app = FastAPI(title="XAU/USD Trading Bot", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

for router in (
    auth.router,
    account.router,
    positions.router,
    trades.router,
    equity.router,
    strategy_config.router,
    risk_config.router,
    bot_state.router,
    live_gate.router,
    kill_switch.router,
    backtest.router,
):
    app.include_router(router)

app.include_router(web_routes.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
