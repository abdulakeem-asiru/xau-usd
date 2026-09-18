from fastapi import APIRouter, Depends

from app.api.deps import get_broker, get_current_user

router = APIRouter()


@router.get("/api/positions")
async def list_positions(user: str = Depends(get_current_user), broker=Depends(get_broker)):
    positions = await broker.get_open_positions()
    return [p.model_dump() for p in positions]
