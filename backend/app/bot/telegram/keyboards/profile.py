from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import buttons
from app.services.profile_service import ProfileKind


class ProfileCallback(CallbackData, prefix="profile"):
    kind: ProfileKind


def profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.PROFILE_CURRENT_SEASON,
        callback_data=ProfileCallback(kind=ProfileKind.CURRENT_SEASON),
    )
    builder.button(
        text=buttons.PROFILE_ALL_TIME,
        callback_data=ProfileCallback(kind=ProfileKind.ALL_TIME),
    )
    builder.adjust(1)
    return builder.as_markup()
