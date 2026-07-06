from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.rating_service import RatingKind


class RatingCallback(CallbackData, prefix="rating"):
    kind: RatingKind


def rating_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Текущий сезон",
        callback_data=RatingCallback(kind=RatingKind.CURRENT_SEASON),
    )
    builder.button(
        text="За все время",
        callback_data=RatingCallback(kind=RatingKind.ALL_TIME),
    )
    builder.button(
        text="Нокауты",
        callback_data=RatingCallback(kind=RatingKind.KNOCKOUTS_CURRENT_SEASON),
    )
    builder.button(
        text="Нокауты за время",
        callback_data=RatingCallback(kind=RatingKind.KNOCKOUTS_ALL_TIME),
    )
    builder.adjust(1)
    return builder.as_markup()
