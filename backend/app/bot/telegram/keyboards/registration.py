from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.states import RegistrationMode


class RegistrationModeCallback(CallbackData, prefix="registration_mode"):
    mode: RegistrationMode


CONFIRM_REGISTRATION_CALLBACK = "registration:confirm"
RESTART_REGISTRATION_CALLBACK = "registration:restart"


def registration_mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Фамилия и имя",
        callback_data=RegistrationModeCallback(mode=RegistrationMode.FULL_NAME),
    )
    builder.button(
        text="Никнейм",
        callback_data=RegistrationModeCallback(mode=RegistrationMode.NICKNAME),
    )
    builder.button(
        text="Фамилия и имя + никнейм",
        callback_data=RegistrationModeCallback(mode=RegistrationMode.BOTH),
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data=CONFIRM_REGISTRATION_CALLBACK)
    builder.button(text="Ввести заново", callback_data=RESTART_REGISTRATION_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()
