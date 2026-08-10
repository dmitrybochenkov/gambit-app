from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.services.dto.seasons import SeasonOptionView
from app.services.pagination import Page
from app.services.rating_service import RatingKind

RATING_PAGE_SIZE = 10
RATING_SEASON_PAGE_SIZE = 5


class RatingCallback(CallbackData, prefix="rating"):
    kind: RatingKind
    page: int = 0
    season_id: int = 0
    season_page: int = 0


class RatingSeasonPageCallback(CallbackData, prefix="rating_sp"):
    kind: RatingKind
    page: int = 0


class RatingSeasonCallback(CallbackData, prefix="rating_s"):
    kind: RatingKind
    season_id: int
    season_page: int = 0


class RatingCancelAction(StrEnum):
    CANCEL = "cancel"
    CLOSE = "close"
    BACK = "back"


class RatingCancelCallback(CallbackData, prefix="rating_cancel"):
    action: RatingCancelAction


def rating_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.RATING_CURRENT_SEASON,
        callback_data=RatingCallback(kind=RatingKind.CURRENT_SEASON, page=-1),
    )
    builder.button(
        text=labels.RATING_SELECTED_SEASON,
        callback_data=RatingSeasonPageCallback(kind=RatingKind.SELECTED_SEASON, page=0),
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
        text=labels.RATING_KNOCKOUTS_SELECTED_SEASON,
        callback_data=RatingSeasonPageCallback(
            kind=RatingKind.KNOCKOUTS_SELECTED_SEASON,
            page=0,
        ),
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
    *,
    season_id: int = 0,
    season_page: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=RatingCallback(
                kind=kind,
                page=page.previous_page,
                season_id=season_id,
                season_page=season_page,
            ),
        )
    builder.button(
        text=_rating_page_label(page),
        callback_data=RatingCallback(
            kind=kind,
            page=page.page,
            season_id=season_id,
            season_page=season_page,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=RatingCallback(
                kind=kind,
                page=page.next_page,
                season_id=season_id,
                season_page=season_page,
            ),
        )
    if kind in {RatingKind.SELECTED_SEASON, RatingKind.KNOCKOUTS_SELECTED_SEASON}:
        builder.button(
            text=labels.ADMIN_PANEL_BACK,
            callback_data=RatingSeasonPageCallback(kind=kind, page=season_page),
        )
    else:
        builder.button(
            text=labels.ADMIN_PANEL_BACK,
            callback_data=RatingCancelCallback(action=RatingCancelAction.BACK),
        )
    builder.button(
        text=labels.RATING_CLOSE,
        callback_data=RatingCancelCallback(action=RatingCancelAction.CLOSE),
    )
    navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
    builder.adjust(navigation_buttons, 1, 1)
    return builder.as_markup()


def rating_seasons_keyboard(
    kind: RatingKind,
    page: Page[SeasonOptionView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for season in page.items:
        builder.button(
            text=season.name,
            callback_data=RatingSeasonCallback(
                kind=kind,
                season_id=season.id,
                season_page=page.page,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=RatingSeasonPageCallback(kind=kind, page=page.previous_page),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=RatingSeasonPageCallback(kind=kind, page=page.page),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=RatingSeasonPageCallback(kind=kind, page=page.next_page),
            )
    builder.button(
        text=labels.ADMIN_PANEL_BACK,
        callback_data=RatingCancelCallback(action=RatingCancelAction.BACK),
    )
    builder.button(
        text=labels.CANCEL,
        callback_data=RatingCancelCallback(action=RatingCancelAction.CANCEL),
    )
    builder.adjust(*([1] * len(page.items)), _season_navigation_width(page), 1, 1)
    return builder.as_markup()


def _rating_page_label(page: Page) -> str:
    if page.total_items == 0:
        return "0 из 0"
    start = page.page * page.page_size + 1
    end = start + len(page.items) - 1
    return f"{start}-{end} из {page.total_items}"


def _season_navigation_width(page: Page) -> int:
    return 1 + int(page.has_previous) + int(page.has_next) if page.total_pages > 1 else 1
