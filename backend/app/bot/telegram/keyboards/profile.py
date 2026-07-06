from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.profile_service import ProfileKind


class ProfileCallback(CallbackData, prefix="profile"):
    kind: ProfileKind


def profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="За текущий сезон",
        callback_data=ProfileCallback(kind=ProfileKind.CURRENT_SEASON),
    )
    builder.button(
        text="За все время",
        callback_data=ProfileCallback(kind=ProfileKind.ALL_TIME),
    )
    builder.adjust(1)
    return builder.as_markup()
