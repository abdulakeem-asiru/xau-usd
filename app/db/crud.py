from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BacktestRun, BacktestTrade, BotConfig, CircuitBreakerState, EquitySnapshot, Trade


# --- bot_config (singleton row) -------------------------------------------------

async def get_bot_config(db: AsyncSession) -> BotConfig:
    result = await db.execute(select(BotConfig).where(BotConfig.id == 1))
    config = result.scalar_one_or_none()
    if config is None:
        config = BotConfig(id=1)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


async def update_bot_config(db: AsyncSession, **fields) -> BotConfig:
    config = await get_bot_config(db)
    for key, value in fields.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return config


# --- trades -----------------------------------------------------------------

async def create_trade(db: AsyncSession, **fields) -> Trade:
    trade = Trade(**fields)
    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    return trade


async def get_trade(db: AsyncSession, trade_id: int) -> Trade | None:
    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    return result.scalar_one_or_none()


async def get_open_trades(db: AsyncSession) -> list[Trade]:
    result = await db.execute(select(Trade).where(Trade.status == "open"))
    return list(result.scalars().all())


async def get_trade_by_broker_id(db: AsyncSession, broker_trade_id: str) -> Trade | None:
    result = await db.execute(select(Trade).where(Trade.broker_trade_id == broker_trade_id))
    return result.scalar_one_or_none()


async def list_trades(db: AsyncSession, status: str | None = None, limit: int = 50, offset: int = 0) -> list[Trade]:
    stmt = select(Trade).order_by(Trade.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Trade.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_trade(db: AsyncSession, trade: Trade, **fields) -> Trade:
    for key, value in fields.items():
        setattr(trade, key, value)
    await db.commit()
    await db.refresh(trade)
    return trade


# --- equity snapshots ---------------------------------------------------------

async def add_equity_snapshot(
    db: AsyncSession, balance: float, equity: float, open_positions_count: int, mode: str
) -> EquitySnapshot:
    snapshot = EquitySnapshot(
        ts=datetime.now(timezone.utc),
        balance=balance,
        equity=equity,
        open_positions_count=open_positions_count,
        mode=mode,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_equity_curve(db: AsyncSession, limit: int = 500) -> list[EquitySnapshot]:
    result = await db.execute(select(EquitySnapshot).order_by(EquitySnapshot.ts.desc()).limit(limit))
    return list(reversed(result.scalars().all()))


# --- circuit breaker -----------------------------------------------------------

async def get_or_create_todays_circuit_breaker(db: AsyncSession, starting_equity: float) -> CircuitBreakerState:
    today = date.today()
    result = await db.execute(select(CircuitBreakerState).where(CircuitBreakerState.trading_day == today))
    state = result.scalar_one_or_none()
    if state is None:
        state = CircuitBreakerState(trading_day=today, starting_equity=starting_equity)
        db.add(state)
        await db.commit()
        await db.refresh(state)
    return state


async def update_circuit_breaker(db: AsyncSession, state: CircuitBreakerState, **fields) -> CircuitBreakerState:
    for key, value in fields.items():
        setattr(state, key, value)
    await db.commit()
    await db.refresh(state)
    return state


# --- backtests ------------------------------------------------------------------

async def create_backtest_run(db: AsyncSession, **fields) -> BacktestRun:
    run = BacktestRun(**fields)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def update_backtest_run(db: AsyncSession, run: BacktestRun, **fields) -> BacktestRun:
    for key, value in fields.items():
        setattr(run, key, value)
    await db.commit()
    await db.refresh(run)
    return run


async def get_backtest_run(db: AsyncSession, run_id: int) -> BacktestRun | None:
    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    return result.scalar_one_or_none()


async def add_backtest_trades(db: AsyncSession, backtest_run_id: int, trades: list[dict]) -> None:
    db.add_all([BacktestTrade(backtest_run_id=backtest_run_id, **t) for t in trades])
    await db.commit()


async def get_backtest_trades(db: AsyncSession, backtest_run_id: int) -> list[BacktestTrade]:
    result = await db.execute(
        select(BacktestTrade).where(BacktestTrade.backtest_run_id == backtest_run_id).order_by(BacktestTrade.entry_time)
    )
    return list(result.scalars().all())
