import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.bot.telegram import notifications
from app.bot.telegram.formatters import check_in as check_in_fmt
from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.texts.superadmin import tournaments as tournament_text
from app.services.business_notification_use_cases import (
    CheckInNotificationDelivery,
    PlayerRewardNotificationDelivery,
    TournamentCancellationDelivery,
)
from app.services.dto.rewards import (
    PlayerRewardCorrectionNotificationView,
    PlayerRewardNotificationView,
)
from app.services.dto.tournaments import TournamentCancellationNotificationView
from app.services.tournament_check_in_service import CheckInResultView
from app.services.user_access_service import UserAccessService, user_access_service

logger = logging.getLogger(__name__)


class TelegramCheckInNotificationDelivery(CheckInNotificationDelivery):
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def deliver(self, result: CheckInResultView) -> None:
        telegram_id = result.user.telegram_id
        if telegram_id is None or telegram_id <= 0:
            return
        try:
            await self._bot.send_message(
                chat_id=telegram_id,
                text=check_in_fmt.player_notification(result.tournament),
            )
        except TelegramAPIError:
            logger.info(
                "Failed to send check-in notification",
                extra={"user_id": result.user.id, "tournament_id": result.tournament.id},
                exc_info=True,
            )


class TelegramTournamentCancellationDelivery(TournamentCancellationDelivery):
    def __init__(
        self,
        bot: Bot,
        users: UserAccessService = user_access_service,
    ) -> None:
        self._bot = bot
        self._users = users

    async def deliver(
        self,
        notifications_: tuple[TournamentCancellationNotificationView, ...],
    ) -> None:
        for notification in notifications_:
            try:
                user = await self._users.get_by_id(notification.user_id)
                if user is None or user.telegram_id is None or user.telegram_id <= 0:
                    continue
                await self._bot.send_message(
                    chat_id=user.telegram_id,
                    text=tournament_text.CALENDAR_TOURNAMENT_CANCELLED_USER.format(
                        tournament=tournament_fmt.label(notification.tournament)
                    ),
                )
            except TelegramAPIError:
                logger.info(
                    "Failed to send tournament cancellation notification",
                    extra={
                        "user_id": notification.user_id,
                        "tournament_id": notification.tournament.id,
                    },
                    exc_info=True,
                )


class TelegramPlayerRewardNotificationDelivery(PlayerRewardNotificationDelivery):
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def deliver_issued(
        self,
        rewards: tuple[PlayerRewardNotificationView, ...],
    ) -> None:
        await notifications.notify_players_about_prize_stack_bonuses(self._bot, rewards)

    async def deliver_corrections(
        self,
        rewards: tuple[PlayerRewardCorrectionNotificationView, ...],
    ) -> None:
        await notifications.notify_players_about_prize_stack_bonus_corrections(
            self._bot,
            rewards,
        )
