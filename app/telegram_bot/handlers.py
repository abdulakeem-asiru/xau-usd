from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.core.enums import CloseReason, TradeStatus
from app.db import crud
from app.db.base import async_session_maker
from app.telegram_bot.auth import is_owner


async def _reject_if_not_owner(update: Update, settings: Settings) -> bool:
    if not is_owner(update, settings):
        await update.message.reply_text("Unauthorized.")
        return True
    return False


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if await _reject_if_not_owner(update, settings):
        return
    broker = context.bot_data["broker"]

    async with async_session_maker() as db:
        config = await crud.get_bot_config(db)
        account = await broker.get_account_summary()
        breaker_row = await crud.get_or_create_todays_circuit_breaker(db, account.equity)
        open_trades = await crud.get_open_trades(db)

    state = "PAUSED" if config.is_paused else ("RUNNING" if config.is_running else "STOPPED")
    lines = [
        f"Status: {state} | mode: {config.mode.upper()}",
        f"Strategy: {config.strategy_name}",
        f"Balance: {account.balance:.2f} | Equity: {account.equity:.2f}",
        f"Open positions: {len(open_trades)} (max {config.max_concurrent_positions})",
        f"Today's PnL: {float(breaker_row.realized_pnl_today):+.2f}"
        + (" — HALTED" if breaker_row.halted else ""),
    ]
    await update.message.reply_text("\n".join(lines))


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if await _reject_if_not_owner(update, settings):
        return
    async with async_session_maker() as db:
        await crud.update_bot_config(db, is_paused=True)
    await update.message.reply_text("⏸ Bot paused — no new entries will be opened. Existing positions still managed.")


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if await _reject_if_not_owner(update, settings):
        return
    async with async_session_maker() as db:
        await crud.update_bot_config(db, is_paused=False)
    await update.message.reply_text("▶️ Bot resumed.")


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if await _reject_if_not_owner(update, settings):
        return
    broker = context.bot_data["broker"]
    account = await broker.get_account_summary()
    await update.message.reply_text(
        f"Balance: {account.balance:.2f} {account.currency}\n"
        f"Equity: {account.equity:.2f}\n"
        f"Margin available: {account.margin_available:.2f}"
    )


async def close_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if await _reject_if_not_owner(update, settings):
        return
    if not context.args:
        await update.message.reply_text("Usage: /close <trade_id>")
        return
    try:
        trade_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("trade_id must be a number — see /status or the dashboard for open trade IDs.")
        return

    broker = context.bot_data["broker"]
    async with async_session_maker() as db:
        trade = await crud.get_trade(db, trade_id)
        if trade is None or trade.status != TradeStatus.OPEN:
            await update.message.reply_text(f"No open trade with id {trade_id}.")
            return

        fill_price = await broker.close_position(trade.broker_trade_id)
        spec = await broker.get_symbol_specification(trade.instrument)
        diff = fill_price - float(trade.entry_price) if trade.side == "buy" else float(trade.entry_price) - fill_price
        pnl = diff * float(trade.volume) * spec.contract_size
        await crud.update_trade(
            db,
            trade,
            status=TradeStatus.CLOSED,
            exit_price=fill_price,
            pnl=pnl,
            close_reason=CloseReason.MANUAL,
            closed_at=datetime.now(timezone.utc),
        )
    await update.message.reply_text(f"Closed trade #{trade_id} @ {fill_price:.2f} | PnL {pnl:+.2f}")
