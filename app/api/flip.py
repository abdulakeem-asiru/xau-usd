from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_notifier
from app.db import crud

router = APIRouter()


class FlipConfigUpdate(BaseModel):
    flip_mode: bool
    flip_risk_pct: float
    flip_equity_floor: float
    flip_equity_target: float

    @field_validator("flip_risk_pct")
    @classmethod
    def _risk_pct_bounds(cls, v: float) -> float:
        # Sizing tolerates a minimum-lot trade risking up to 1.5x this figure, so 15% here
        # means a single stop-out can cost ~22% of equity — that is the ceiling, not a default.
        if not (0 < v <= 15):
            raise ValueError("flip_risk_pct must be between 0 and 15 (percent)")
        return v

    @field_validator("flip_equity_floor")
    @classmethod
    def _floor_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("flip_equity_floor must be positive")
        return v

    @model_validator(mode="after")
    def _target_above_floor(self):
        if self.flip_equity_target <= self.flip_equity_floor:
            raise ValueError("flip_equity_target must be above flip_equity_floor")
        return self


def _flip_config_dict(config) -> dict:
    return {
        "flip_mode": config.flip_mode,
        "flip_risk_pct": float(config.flip_risk_pct),
        "flip_equity_floor": float(config.flip_equity_floor),
        "flip_equity_target": float(config.flip_equity_target),
        "is_paused": config.is_paused,
    }


@router.get("/api/config/flip")
async def get_flip_config(user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return _flip_config_dict(await crud.get_bot_config(db))


@router.put("/api/config/flip")
async def update_flip_config(
    payload: FlipConfigUpdate,
    user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    notify=Depends(get_notifier),
):
    was_on = (await crud.get_bot_config(db)).flip_mode
    config = await crud.update_bot_config(
        db,
        flip_mode=payload.flip_mode,
        flip_risk_pct=payload.flip_risk_pct,
        flip_equity_floor=payload.flip_equity_floor,
        flip_equity_target=payload.flip_equity_target,
    )
    if config.flip_mode and not was_on:
        await notify(
            f"🎲 Flip mode ON — risking {payload.flip_risk_pct:g}% per trade; entries stop at equity "
            f"{payload.flip_equity_floor:g} (floor) or {payload.flip_equity_target:g} (target)."
        )
    elif was_on and not config.flip_mode:
        await notify("Flip mode OFF — back to the normal risk limits.")
    return _flip_config_dict(config)
