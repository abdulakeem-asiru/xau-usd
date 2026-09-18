import logging

from telegram import Bot

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Implements the `Notifier` callable contract (`Callable[[str], Awaitable[None]]`)
    used throughout `app.engine` — pass `notifier.send` wherever a Notifier is expected.
    Never raises: a failed notification must not take down the trading loop.
    """

    def __init__(self, bot: Bot, chat_id: str):
        self._bot = bot
        self._chat_id = chat_id

    async def send(self, message: str) -> None:
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=message)
        except Exception:
            logger.exception("Failed to send Telegram notification")
