import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from app.bot.telegram.handlers.admin import router as admin_router
from app.bot.telegram.handlers.superadmin import router as superadmin_router
from app.bot.telegram.handlers.user import router as user_router
from app.config import settings

logger = logging.getLogger(__name__)

telegram_dispatcher = Dispatcher(storage=MemoryStorage())
telegram_dispatcher.include_router(superadmin_router)
telegram_dispatcher.include_router(admin_router)
telegram_dispatcher.include_router(user_router)

telegram_bot = Bot(token=settings.telegram_bot_token) if settings.telegram_bot_token else None


@telegram_dispatcher.errors()
async def telegram_error_boundary(event: ErrorEvent) -> bool:
    update = event.update
    callback = update.callback_query
    message = update.message
    user_id = None
    chat_id = None
    update_kind = "unknown"
    callback_data = None
    command = None
    if callback is not None:
        update_kind = "callback_query"
        user_id = callback.from_user.id
        callback_data = callback.data
        if callback.message is not None:
            chat_id = callback.message.chat.id
    elif message is not None:
        update_kind = "message"
        user_id = message.from_user.id if message.from_user is not None else None
        chat_id = message.chat.id
        command = message.text

    logger.exception(
        "Unhandled Telegram update error",
        extra={
            "update_id": update.update_id,
            "update_kind": update_kind,
            "telegram_user_id": user_id,
            "chat_id": chat_id,
            "callback_data": callback_data,
            "command": command,
        },
        exc_info=event.exception,
    )
    await _send_safe_fallback(callback=callback, message=message)
    return True


async def _send_safe_fallback(callback: object | None, message: object | None) -> None:
    text = "Не удалось выполнить действие. Попробуйте ещё раз."
    if callback is not None:
        try:
            await callback.answer(text, show_alert=True)
        except TelegramBadRequest as exc:
            message_text = str(exc).lower()
            if "query is too old" in message_text or "query id is invalid" in message_text:
                logger.info("Telegram callback fallback was not delivered: %s", exc)
                return
            logger.exception("Telegram callback fallback failed")
        except TelegramAPIError:
            logger.exception("Telegram callback fallback failed")
        return
    if message is not None:
        try:
            await message.answer(text)
        except TelegramAPIError:
            logger.exception("Telegram message fallback failed")


async def setup_telegram_webhook() -> None:
    public_base_url = settings.effective_public_base_url
    if telegram_bot is None or not public_base_url:
        return
    if not settings.telegram_webhook_secret:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is required when PUBLIC_BASE_URL is set")

    await telegram_bot.set_webhook(
        url=f"{public_base_url}/webhooks/tg",
        secret_token=settings.telegram_webhook_secret,
        drop_pending_updates=True,
        allowed_updates=telegram_dispatcher.resolve_used_update_types(),
    )


async def shutdown_telegram_bot() -> None:
    if telegram_bot is None:
        return

    await telegram_bot.session.close()
