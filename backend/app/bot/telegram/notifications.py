from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.bot.telegram import keyboards, texts
from app.services.dto import PlayerView, RegistrationMatchView
from app.services.player_service import player_service


def format_registration_review(
    player: PlayerView,
    matches: list[RegistrationMatchView] | None = None,
) -> str:
    return texts.admin.registration_review(player, matches or [])


async def notify_admins_about_registration(bot: Bot, player: PlayerView) -> None:
    notification = await player_service.get_registration_notification(player.id)
    text = format_registration_review(notification.player, notification.matches)
    keyboard = keyboards.registration_review_keyboard(
        notification.player.id,
        has_matches=bool(notification.matches),
    )

    for admin in notification.admins:
        try:
            await bot.send_message(
                chat_id=admin.telegram_id,
                text=text,
                reply_markup=keyboard,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            continue
