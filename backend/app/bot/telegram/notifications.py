from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.bot.telegram.keyboards.superadmin import registrations as superadmin_registrations_kb
from app.bot.telegram.texts.superadmin import registrations as registration_text
from app.services.dto import RegistrationReviewView
from app.services.user_service import user_service


def format_registration_review(review: RegistrationReviewView) -> str:
    return registration_text.registration_review(review)


async def notify_admins_about_registration(bot: Bot, request_id: int) -> None:
    notification = await user_service.get_registration_notification(request_id)
    review = RegistrationReviewView(
        request=notification.request,
        candidates=notification.candidates,
    )
    text = format_registration_review(review)
    keyboard = superadmin_registrations_kb.registration_review_keyboard(
        notification.request.id,
        can_edit_name=notification.request.request_type == "new_player",
        can_select_candidate=notification.request.request_type == "link_existing_player",
    )

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
