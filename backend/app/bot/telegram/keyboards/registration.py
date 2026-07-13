from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import buttons
from app.bot.telegram.states import RegistrationMode


class RegistrationModeCallback(CallbackData, prefix="registration_mode"):
    mode: RegistrationMode


CONFIRM_REGISTRATION_CALLBACK = "registration:confirm"
RESTART_REGISTRATION_CALLBACK = "registration:restart"


def registration_mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.REGISTRATION_FULL_NAME,
        callback_data=RegistrationModeCallback(mode=RegistrationMode.FULL_NAME),
    )
    builder.button(
        text=buttons.REGISTRATION_NICKNAME,
        callback_data=RegistrationModeCallback(mode=RegistrationMode.NICKNAME),
    )
    builder.button(
        text=buttons.REGISTRATION_BOTH,
        callback_data=RegistrationModeCallback(mode=RegistrationMode.BOTH),
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=buttons.CONFIRM, callback_data=CONFIRM_REGISTRATION_CALLBACK)
    builder.button(text=buttons.RESTART, callback_data=RESTART_REGISTRATION_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()
