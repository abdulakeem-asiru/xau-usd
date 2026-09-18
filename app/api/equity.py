from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db import crud

router = APIRouter()


@router.get("/api/equity-curve")
async def equity_curve(limit: int = 500, user: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    snapshots = await crud.get_equity_curve(db, limit=limit)
    return [
        {
            "ts": s.ts.isoformat(),
            "balance": float(s.balance),
            "equity": float(s.equity),
            "open_positions_count": s.open_positions_count,
            "mode": s.mode,
        }
        for s in snapshots
    ]
