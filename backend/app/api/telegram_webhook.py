import json
import logging

from fastapi import APIRouter, Header, HTTPException, status

from app.bot.telegram.runtime import telegram_bot, telegram_dispatcher
from app.config import settings

router = APIRouter(prefix="/webhooks/tg", tags=["telegram"])
logger = logging.getLogger(__name__)


@router.post("")
async def telegram_webhook(
    payload: dict,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if telegram_bot is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not configured",
        )

    if (
        not settings.telegram_webhook_secret
        or x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Telegram webhook secret",
        )

    _log_telegram_chat_destination(payload)
    await telegram_dispatcher.feed_raw_update(telegram_bot, payload)
    return {"ok": True}


def _log_telegram_chat_destination(payload: dict) -> None:
    try:
        for update_type in ("message", "channel_post"):
            update = payload.get(update_type)
            if not isinstance(update, dict):
                continue
            chat = update.get("chat")
            if not isinstance(chat, dict):
                continue
            chat_id = chat.get("id")
            chat_type = chat.get("type")
            title = chat.get("title")
            if chat_id is None or chat_type is None or not isinstance(title, str):
                continue
            logger.info(
                "TG_CHAT_DESTINATION id=%s type=%s title=%s",
                chat_id,
                chat_type,
                json.dumps(title, ensure_ascii=False),
            )
    except Exception:
        logger.debug("Failed to log Telegram chat destination metadata", exc_info=True)
