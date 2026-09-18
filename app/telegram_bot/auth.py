from telegram import Update

from app.config import Settings


def is_owner(update: Update, settings: Settings) -> bool:
    chat = update.effective_chat
    return chat is not None and str(chat.id) == str(settings.owner_telegram_chat_id)
