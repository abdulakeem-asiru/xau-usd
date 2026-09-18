from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db import crud

router = APIRouter()


class RiskConfigUpdate(BaseModel):
    risk_pct_per_trade: float
    max_daily_loss_pct: float
    max_concurrent_positions: int

    @field_validator("risk_pct_per_trade")
    @classmethod
    def _risk_pct_bounds(cls, v: float) -> float:
        # Hard sanity cap — a fat-fingered 50% risk-per-trade should be rejected outright,
        # not silently accepted and left for the trading loop to enforce.
        if not (0 < v <= 10):
            raise ValueError("risk_pct_per_trade must be between 0 and 10 (percent)")
        return v

    @field_validator("max_daily_loss_pct")
    @classmethod
    def _daily_loss_bounds(cls, v: float) -> float:
        if not (0 < v <= 20):
            raise ValueError("max_daily_loss_pct must be between 0 and 20 (percent)")
        return v

    @field_validator("max_concurrent_positions")
    @classmethod
    def _positions_bounds(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_concurrent_positions must be at least 1")
        return v


@router.get("/api/config/risk")
async def get_risk_config(user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    config = await crud.get_bot_config(db)
    return {
        "risk_pct_per_trade": float(config.risk_pct_per_trade),
        "max_daily_loss_pct": float(config.max_daily_loss_pct),
        "max_concurrent_positions": config.max_concurrent_positions,
    }


@router.put("/api/config/risk")
async def update_risk_config(
    payload: RiskConfigUpdate, user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    config = await crud.update_bot_config(
        db,
        risk_pct_per_trade=payload.risk_pct_per_trade,
        max_daily_loss_pct=payload.max_daily_loss_pct,
        max_concurrent_positions=payload.max_concurrent_positions,
    )
    return {
        "risk_pct_per_trade": float(config.risk_pct_per_trade),
        "max_daily_loss_pct": float(config.max_daily_loss_pct),
        "max_concurrent_positions": config.max_concurrent_positions,
    }
