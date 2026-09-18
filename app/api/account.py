from fastapi import APIRouter, Depends

from app.api.deps import get_broker, get_current_user

router = APIRouter()


@router.get("/api/account")
async def account_summary(user: str = Depends(get_current_user), broker=Depends(get_broker)):
    summary = await broker.get_account_summary()
    return summary.model_dump()
