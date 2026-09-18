from telegram import Update
from telegram.ext import Application, CommandHandler

from app.broker.interface import BrokerProtocol
from app.config import Settings
from app.telegram_bot import handlers


def build_application(settings: Settings, broker: BrokerProtocol) -> Application:
    # updater=None: we're not polling — updates arrive via the /telegram/webhook route
    # and get fed in manually with application.process_update().
    application = Application.builder().token(settings.telegram_bot_token).updater(None).build()
    application.bot_data["broker"] = broker
    application.bot_data["settings"] = settings

    application.add_handler(CommandHandler("status", handlers.status))
    application.add_handler(CommandHandler("pause", handlers.pause))
    application.add_handler(CommandHandler("resume", handlers.resume))
    application.add_handler(CommandHandler("close", handlers.close_trade))
    application.add_handler(CommandHandler("balance", handlers.balance))
    return application


async def setup_webhook(application: Application, settings: Settings) -> None:
    url = f"{settings.telegram_webhook_base_url.rstrip('/')}/telegram/webhook/{settings.telegram_webhook_secret}"
    await application.bot.set_webhook(url=url, allowed_updates=Update.ALL_TYPES)
