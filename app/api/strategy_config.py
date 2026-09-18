from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db import crud
from app.strategy.registry import STRATEGY_REGISTRY

router = APIRouter()


class StrategyConfigUpdate(BaseModel):
    strategy_name: str
    strategy_params: dict = {}


@router.get("/api/config/strategy")
async def get_strategy_config(user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    config = await crud.get_bot_config(db)
    return {
        "strategy_name": config.strategy_name,
        "strategy_params": config.strategy_params,
        "available_strategies": list(STRATEGY_REGISTRY),
    }


@router.put("/api/config/strategy")
async def update_strategy_config(
    payload: StrategyConfigUpdate, user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if payload.strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown strategy '{payload.strategy_name}'")
    # Fail fast on bad params now rather than letting the live loop silently no-op later.
    try:
        STRATEGY_REGISTRY[payload.strategy_name](payload.strategy_params)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid strategy_params: {exc}") from exc

    config = await crud.update_bot_config(
        db, strategy_name=payload.strategy_name, strategy_params=payload.strategy_params
    )
    return {"strategy_name": config.strategy_name, "strategy_params": config.strategy_params}
