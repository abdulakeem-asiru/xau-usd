from fastapi import APIRouter, Request, Response
from telegram import Update
from telegram.ext import Application

router = APIRouter()


def register_webhook_route(app_router: APIRouter, telegram_app: Application, webhook_secret: str) -> None:
    @app_router.post(f"/telegram/webhook/{webhook_secret}")
    async def telegram_webhook(request: Request) -> Response:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
        return Response(status_code=200)
