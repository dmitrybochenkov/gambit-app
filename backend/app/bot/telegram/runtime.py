from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.telegram.handlers.admin import router as admin_router
from app.bot.telegram.handlers.superadmin import router as superadmin_router
from app.bot.telegram.handlers.user import router as user_router
from app.config import settings

telegram_dispatcher = Dispatcher(storage=MemoryStorage())
telegram_dispatcher.include_router(superadmin_router)
telegram_dispatcher.include_router(admin_router)
telegram_dispatcher.include_router(user_router)

telegram_bot = Bot(token=settings.telegram_bot_token) if settings.telegram_bot_token else None


async def setup_telegram_webhook() -> None:
    public_base_url = settings.effective_public_base_url
    if telegram_bot is None or not public_base_url:
        return

    await telegram_bot.set_webhook(
        url=f"{public_base_url}/webhooks/tg",
        secret_token=settings.telegram_webhook_secret or None,
        drop_pending_updates=True,
        allowed_updates=telegram_dispatcher.resolve_used_update_types(),
    )


async def shutdown_telegram_bot() -> None:
    if telegram_bot is None:
        return

    await telegram_bot.session.close()
