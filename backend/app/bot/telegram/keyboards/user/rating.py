from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.services.pagination import Page
from app.services.rating_service import RatingKind

RATING_PAGE_SIZE = 10


class RatingCallback(CallbackData, prefix="rating"):
    kind: RatingKind
    page: int = 0


class RatingCancelAction(StrEnum):
    CANCEL = "cancel"
    CLOSE = "close"


class RatingCancelCallback(CallbackData, prefix="rating_cancel"):
    action: RatingCancelAction


def rating_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.RATING_CURRENT_SEASON,
        callback_data=RatingCallback(kind=RatingKind.CURRENT_SEASON, page=-1),
    )
    builder.button(
        text=labels.RATING_ALL_TIME,
        callback_data=RatingCallback(kind=RatingKind.ALL_TIME, page=-1),
    )
    builder.button(
        text=labels.RATING_KNOCKOUTS_CURRENT_SEASON,
        callback_data=RatingCallback(kind=RatingKind.KNOCKOUTS_CURRENT_SEASON, page=-1),
    )
    builder.button(
        text=labels.RATING_KNOCKOUTS_ALL_TIME,
        callback_data=RatingCallback(kind=RatingKind.KNOCKOUTS_ALL_TIME, page=-1),
    )
    builder.button(
        text=labels.CANCEL,
        callback_data=RatingCancelCallback(action=RatingCancelAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def rating_page_keyboard(
    kind: RatingKind,
    page: Page,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=RatingCallback(kind=kind, page=page.previous_page),
        )
    builder.button(
        text=_rating_page_label(page),
        callback_data=RatingCallback(kind=kind, page=page.page),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=RatingCallback(kind=kind, page=page.next_page),
        )
    builder.button(
        text=labels.RATING_CLOSE,
        callback_data=RatingCancelCallback(action=RatingCancelAction.CLOSE),
    )
    navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
    builder.adjust(navigation_buttons, 1)
    return builder.as_markup()


def _rating_page_label(page: Page) -> str:
    if page.total_items == 0:
        return "0 из 0"
    start = page.page * page.page_size + 1
    end = start + len(page.items) - 1
    return f"{start}-{end} из {page.total_items}"
