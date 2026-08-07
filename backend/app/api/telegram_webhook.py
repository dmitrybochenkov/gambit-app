from fastapi import APIRouter, Header, HTTPException, status

from app.bot.telegram.runtime import telegram_bot, telegram_dispatcher
from app.config import settings

router = APIRouter(prefix="/webhooks/tg", tags=["telegram"])


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

    await telegram_dispatcher.feed_raw_update(telegram_bot, payload)
    return {"ok": True}
