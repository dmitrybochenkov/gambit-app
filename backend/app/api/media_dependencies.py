from app.bot.telegram import runtime
from app.bot.telegram.media_gateway import AiogramTelegramMediaGateway
from app.db.session import SessionFactory
from app.services.media_read_service import MediaReadService


def media_read_service() -> MediaReadService:
    bot = runtime.telegram_bot
    if bot is None:
        raise RuntimeError("Telegram bot is not configured")
    return MediaReadService(SessionFactory, AiogramTelegramMediaGateway(bot))
