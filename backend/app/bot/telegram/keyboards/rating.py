from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import buttons
from app.services.rating_service import RatingKind


class RatingCallback(CallbackData, prefix="rating"):
    kind: RatingKind


def rating_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.RATING_CURRENT_SEASON,
        callback_data=RatingCallback(kind=RatingKind.CURRENT_SEASON),
    )
    builder.button(
        text=buttons.RATING_ALL_TIME,
        callback_data=RatingCallback(kind=RatingKind.ALL_TIME),
    )
    builder.button(
        text=buttons.RATING_KNOCKOUTS_CURRENT_SEASON,
        callback_data=RatingCallback(kind=RatingKind.KNOCKOUTS_CURRENT_SEASON),
    )
    builder.button(
        text=buttons.RATING_KNOCKOUTS_ALL_TIME,
        callback_data=RatingCallback(kind=RatingKind.KNOCKOUTS_ALL_TIME),
    )
    builder.adjust(1)
    return builder.as_markup()
