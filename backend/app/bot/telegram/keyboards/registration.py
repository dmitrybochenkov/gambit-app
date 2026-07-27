from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import buttons

CONFIRM_REGISTRATION_CALLBACK = "registration:confirm"
RESTART_REGISTRATION_CALLBACK = "registration:restart"


def registration_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=buttons.CONFIRM, callback_data=CONFIRM_REGISTRATION_CALLBACK)
    builder.button(text=buttons.RESTART, callback_data=RESTART_REGISTRATION_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()
