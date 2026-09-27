from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ReplyKeyboardRemove

from app.bot.telegram.keyboards.user import menu as user_menu_kb
from app.bot.telegram.notifications import format_registration_review
from app.bot.telegram.texts.superadmin import registrations as superadmin_text
from app.bot.telegram.texts.user import registration as user_text
from app.services.dto.registrations import (
    RegistrationReviewDecision,
    RegistrationReviewOutcomeView,
)


class TelegramRegistrationReviewNotificationDelivery:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def deliver(self, outcome: RegistrationReviewOutcomeView) -> None:
        approved = outcome.decision == RegistrationReviewDecision.APPROVED
        result_text = (
            superadmin_text.REGISTRATION_APPROVED
            if approved
            else superadmin_text.REGISTRATION_REJECTED
        )
        reviewed_text = superadmin_text.reviewed_by_admin(
            review_text=format_registration_review(outcome.review),
            result_text=result_text,
            admin_name=outcome.reviewer.display_name,
        )
        for recipient in outcome.notification_recipients:
            if recipient.telegram_id is None:
                continue
            try:
                await self._bot.send_message(
                    chat_id=recipient.telegram_id,
                    text=reviewed_text,
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                continue

        try:
            applicant_text = (
                user_text.REGISTRATION_APPROVED if approved else user_text.REGISTRATION_REJECTED
            )
            await self._bot.send_message(
                chat_id=outcome.request.telegram_id,
                text=applicant_text,
                reply_markup=(
                    user_menu_kb.main_keyboard_after_registration()
                    if approved
                    else ReplyKeyboardRemove()
                ),
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
