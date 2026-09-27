from app.bot.telegram import runtime
from app.bot.telegram.registration_review_notifications import (
    TelegramRegistrationReviewNotificationDelivery,
)
from app.services.registration_review_use_cases import RegistrationReviewNotificationDelivery


def registration_review_notification_delivery() -> RegistrationReviewNotificationDelivery:
    bot = runtime.telegram_bot
    if bot is None:
        raise RuntimeError("Telegram bot is not configured")
    return TelegramRegistrationReviewNotificationDelivery(bot)
