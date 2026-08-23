import logging
from datetime import date

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

from app.bot.telegram.keyboards.superadmin import registrations as superadmin_registrations_kb
from app.bot.telegram.texts.superadmin import registrations as registration_text
from app.bot.telegram.texts.user import rewards as reward_text
from app.services.dto.registrations import RegistrationReviewView
from app.services.dto.rewards import (
    PlayerRewardCorrectionNotificationView,
    PlayerRewardNotificationView,
)
from app.services.player_reward_service import player_reward_service
from app.services.registration_review_service import registration_review_service

logger = logging.getLogger(__name__)


def format_registration_review(review: RegistrationReviewView) -> str:
    return registration_text.registration_review(review)


async def notify_admins_about_registration(bot: Bot, request_id: int) -> None:
    notification = await registration_review_service.get_registration_notification(request_id)
    review = RegistrationReviewView(
        request=notification.request,
        candidates=notification.candidates,
    )
    text = format_registration_review(review)
    keyboard = superadmin_registrations_kb.registration_review_keyboard_for_review(review)

    for admin in notification.admins:
        if admin.telegram_id is None:
            continue
        try:
            await bot.send_message(
                chat_id=admin.telegram_id,
                text=text,
                reply_markup=keyboard,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            continue


async def notify_players_about_prize_stack_bonuses(
    bot: Bot,
    rewards: tuple[PlayerRewardNotificationView, ...],
) -> None:
    for reward in rewards:
        if reward.telegram_id is None or reward.telegram_id <= 0:
            continue
        try:
            await bot.send_message(
                chat_id=reward.telegram_id,
                text=reward_text.prize_stack_bonus_notification(reward),
            )
        except TelegramAPIError:
            logger.info(
                "Failed to send prize stack bonus notification",
                extra={"reward_id": reward.reward_id},
                exc_info=True,
            )
            continue


async def notify_players_about_prize_stack_bonus_corrections(
    bot: Bot,
    rewards: tuple[PlayerRewardCorrectionNotificationView, ...],
) -> None:
    for reward in rewards:
        if reward.telegram_id is None or reward.telegram_id <= 0:
            continue
        try:
            await bot.send_message(
                chat_id=reward.telegram_id,
                text=reward_text.prize_stack_bonus_correction_notification(reward),
            )
        except TelegramAPIError:
            logger.info(
                "Failed to send prize stack bonus correction notification",
                extra={
                    "player_id": reward.player_id,
                    "source_tournament_id": reward.source_tournament_id,
                },
                exc_info=True,
            )
            continue


async def process_due_reward_expiration_reminders(
    bot: Bot,
    *,
    business_date: date,
) -> None:
    groups = await player_reward_service.list_due_expiration_reminder_groups(
        business_date=business_date
    )
    for group in groups:
        reward_ids = tuple(reward.reward_id for reward in group.rewards)
        refreshed = await player_reward_service.get_due_expiration_reminder_group(
            player_id=group.player_id,
            reward_ids=reward_ids,
            business_date=business_date,
        )
        if refreshed is None:
            continue
        try:
            await bot.send_message(
                chat_id=refreshed.telegram_id,
                text=reward_text.prize_stack_bonus_expiration_reminder(
                    refreshed,
                    business_date,
                ),
            )
        except TelegramAPIError:
            logger.info(
                "Failed to send prize stack bonus expiration reminder",
                extra={"player_id": refreshed.player_id, "reward_ids": reward_ids},
                exc_info=True,
            )
            continue
        await player_reward_service.mark_expiration_reminders_sent(
            reward_ids=tuple(reward.reward_id for reward in refreshed.rewards),
            business_date=business_date,
        )
