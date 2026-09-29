from app.bot.telegram import runtime
from app.bot.telegram.business_notifications import (
    TelegramCheckInNotificationDelivery,
    TelegramPlayerRewardNotificationDelivery,
    TelegramTournamentCancellationDelivery,
)
from app.services.business_notification_use_cases import (
    CheckInNotificationDelivery,
    PlayerRewardNotificationDelivery,
    TournamentCancellationDelivery,
)


def _bot():
    bot = runtime.telegram_bot
    if bot is None:
        raise RuntimeError("Telegram bot is not configured")
    return bot


def check_in_notification_delivery() -> CheckInNotificationDelivery:
    return TelegramCheckInNotificationDelivery(_bot())


def tournament_cancellation_delivery() -> TournamentCancellationDelivery:
    return TelegramTournamentCancellationDelivery(_bot())


def player_reward_notification_delivery() -> PlayerRewardNotificationDelivery:
    return TelegramPlayerRewardNotificationDelivery(_bot())
