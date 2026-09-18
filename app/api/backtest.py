import logging
from datetime import date, datetime, timezone
from math import isfinite

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_broker, get_current_user, get_db
from app.backtest.data_loader import load_historical_candles
from app.backtest.engine import run_backtest
from app.broker.metaapi_client import MetaApiClient
from app.broker.schemas import Candle
from app.db import crud
from app.db.base import async_session_maker
from app.strategy.registry import STRATEGY_REGISTRY, get_strategy

logger = logging.getLogger(__name__)
router = APIRouter()


class BacktestRequest(BaseModel):
    strategy_name: str = "ema_atr_rsi_macd"
    strategy_params: dict = {}
    instrument: str = "XAUUSD"
    timeframe: str = "15m"
    start_date: date
    end_date: date
    initial_balance: float = 10_000
    risk_pct_per_trade: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_concurrent_positions: int = 1
    # Must match your real broker's symbol specification (MT5 terminal → Market Watch →
    # right-click the symbol → Specification) or the backtest's P&L will be inaccurate
    # even if trade timing is correct. 100/0.01/100/0.01 are common XAUUSD defaults.
    contract_size: float = 100.0
    min_volume: float = 0.01
    max_volume: float = 100.0
    volume_step: float = 0.01


def _candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    rows = [{"time": c.time, "open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in candles]
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True)


@router.post("/api/backtest/run")
async def start_backtest(
    payload: BacktestRequest,
    background_tasks: BackgroundTasks,
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    broker: MetaApiClient = Depends(get_broker),
):
    if payload.strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown strategy '{payload.strategy_name}'")
    if payload.end_date <= payload.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_date must be after start_date")

    run = await crud.create_backtest_run(
        db,
        strategy_name=payload.strategy_name,
        params=payload.strategy_params,
        instrument=payload.instrument,
        timeframe=payload.timeframe,
        start_date=payload.start_date,
        end_date=payload.end_date,
        initial_balance=payload.initial_balance,
        status="running",
    )
    background_tasks.add_task(_execute_backtest, run.id, payload, broker)
    return {"backtest_run_id": run.id, "status": "running"}


async def _execute_backtest(run_id: int, payload: BacktestRequest, broker: MetaApiClient) -> None:
    async with async_session_maker() as db:
        run = await crud.get_backtest_run(db, run_id)
        try:
            start_dt = datetime.combine(payload.start_date, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(payload.end_date, datetime.min.time(), tzinfo=timezone.utc)
            candles = await load_historical_candles(broker, payload.instrument, payload.timeframe, start_dt, end_dt)
            df = _candles_to_df(candles)

            strategy = get_strategy(payload.strategy_name, payload.strategy_params)
            result = await run_backtest(
                df=df,
                strategy=strategy,
                instrument=payload.instrument,
                initial_balance=payload.initial_balance,
                risk_pct_per_trade=payload.risk_pct_per_trade,
                max_daily_loss_pct=payload.max_daily_loss_pct,
                max_concurrent_positions=payload.max_concurrent_positions,
                contract_size=payload.contract_size,
                min_volume=payload.min_volume,
                max_volume=payload.max_volume,
                volume_step=payload.volume_step,
            )

            profit_factor = result.metrics["profit_factor"]
            await crud.update_backtest_run(
                db,
                run,
                final_balance=result.final_balance,
                win_rate=result.metrics["win_rate"],
                max_drawdown_pct=result.metrics["max_drawdown_pct"],
                sharpe_ratio=result.metrics["sharpe_ratio"],
                profit_factor=profit_factor if profit_factor is not None and isfinite(profit_factor) else None,
                total_trades=result.metrics["total_trades"],
                status="complete",
            )
            await crud.add_backtest_trades(
                db,
                run.id,
                [
                    {
                        "entry_time": t.entry_time,
                        "exit_time": t.exit_time,
                        "side": t.side,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "pnl": t.pnl,
                        "exit_reason": t.exit_reason,
                    }
                    for t in result.closed_trades
                ],
            )
        except Exception as exc:
            logger.exception("Backtest run #%s failed", run_id)
            await crud.update_backtest_run(db, run, status="failed", error_message=str(exc))


def _backtest_run_to_dict(run) -> dict:
    return {
        "id": run.id,
        "strategy_name": run.strategy_name,
        "params": run.params,
        "instrument": run.instrument,
        "timeframe": run.timeframe,
        "start_date": run.start_date.isoformat(),
        "end_date": run.end_date.isoformat(),
        "initial_balance": float(run.initial_balance),
        "final_balance": float(run.final_balance) if run.final_balance is not None else None,
        "win_rate": float(run.win_rate) if run.win_rate is not None else None,
        "max_drawdown_pct": float(run.max_drawdown_pct) if run.max_drawdown_pct is not None else None,
        "sharpe_ratio": float(run.sharpe_ratio) if run.sharpe_ratio is not None else None,
        "profit_factor": float(run.profit_factor) if run.profit_factor is not None else None,
        "total_trades": run.total_trades,
        "status": run.status,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/api/backtest/{backtest_id}")
async def get_backtest(backtest_id: int, user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await crud.get_backtest_run(db, backtest_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backtest run not found")
    return _backtest_run_to_dict(run)


@router.get("/api/backtest/{backtest_id}/trades")
async def get_backtest_trades(
    backtest_id: int, user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    trades = await crud.get_backtest_trades(db, backtest_id)
    return [
        {
            "id": t.id,
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "side": t.side,
            "entry_price": float(t.entry_price),
            "exit_price": float(t.exit_price) if t.exit_price is not None else None,
            "pnl": float(t.pnl) if t.pnl is not None else None,
            "exit_reason": t.exit_reason,
        }
        for t in trades
    ]
