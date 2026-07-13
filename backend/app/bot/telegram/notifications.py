from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.bot.telegram import keyboards, texts
from app.bot.telegram.formatters import format_admin_calendar_prompt
from app.db.models import AdminPrompt, Player
from app.services.player_service import player_service


def format_registration_review(player: Player) -> str:
    return texts.admin.registration_review(player)


async def notify_admins_about_registration(bot: Bot, player: Player) -> None:
    admins = await player_service.get_active_admins()
    text = format_registration_review(player)
    keyboard = keyboards.registration_review_keyboard(player.id)

    for admin in admins:
        try:
            await bot.send_message(
                chat_id=admin.telegram_id,
                text=text,
                reply_markup=keyboard,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            continue


async def notify_admins_about_calendar_prompt(bot: Bot, prompt: AdminPrompt) -> None:
    admins = await player_service.get_active_admins()
    text = format_admin_calendar_prompt(prompt)
    keyboard = keyboards.calendar_prompt_keyboard(prompt.id)

    for admin in admins:
        try:
            await bot.send_message(
                chat_id=admin.telegram_id,
                text=text,
                reply_markup=keyboard,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            continue
