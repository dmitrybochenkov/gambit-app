from app.bot.telegram import runtime
from app.bot.telegram.admin_management_notifications import (
    TelegramAdminPromotionNotificationDelivery,
)
from app.services.admin_management_use_cases import AdminPromotionNotificationDelivery


def admin_promotion_notification_delivery() -> AdminPromotionNotificationDelivery:
    bot = runtime.telegram_bot
    if bot is None:
        raise RuntimeError("Telegram bot is not configured")
    return TelegramAdminPromotionNotificationDelivery(bot)
