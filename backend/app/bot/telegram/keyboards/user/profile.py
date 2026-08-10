from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.services.dto.seasons import SeasonOptionView
from app.services.pagination import Page
from app.services.profile_service import ProfileKind

PROFILE_SEASON_PAGE_SIZE = 5


class ProfileCallback(CallbackData, prefix="profile"):
    kind: ProfileKind
    season_id: int = 0
    season_page: int = 0


class ProfileSeasonPageCallback(CallbackData, prefix="profile_sp"):
    page: int = 0


class ProfileSeasonCallback(CallbackData, prefix="profile_s"):
    season_id: int
    season_page: int = 0


class ProfileCancelCallback(CallbackData, prefix="profile_cancel"):
    action: str = "cancel"


def profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.PROFILE_CURRENT_SEASON,
        callback_data=ProfileCallback(kind=ProfileKind.CURRENT_SEASON),
    )
    builder.button(
        text=labels.PROFILE_SELECTED_SEASON,
        callback_data=ProfileSeasonPageCallback(page=0),
    )
    builder.button(
        text=labels.PROFILE_ALL_TIME,
        callback_data=ProfileCallback(kind=ProfileKind.ALL_TIME),
    )
    builder.button(
        text=labels.CANCEL,
        callback_data=ProfileCancelCallback(),
    )
    builder.adjust(1)
    return builder.as_markup()


def profile_result_keyboard(
    *,
    kind: ProfileKind,
    season_page: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if kind == ProfileKind.SELECTED_SEASON:
        builder.button(
            text=labels.ADMIN_PANEL_BACK,
            callback_data=ProfileSeasonPageCallback(page=season_page),
        )
    else:
        builder.button(
            text=labels.ADMIN_PANEL_BACK,
            callback_data=ProfileCancelCallback(action="back"),
        )
    builder.button(text="❌ Закрыть", callback_data=ProfileCancelCallback(action="close"))
    builder.adjust(1)
    return builder.as_markup()


def profile_seasons_keyboard(page: Page[SeasonOptionView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for season in page.items:
        builder.button(
            text=season.name,
            callback_data=ProfileSeasonCallback(
                season_id=season.id,
                season_page=page.page,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=ProfileSeasonPageCallback(page=page.previous_page),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=ProfileSeasonPageCallback(page=page.page),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=ProfileSeasonPageCallback(page=page.next_page),
            )
    builder.button(
        text=labels.ADMIN_PANEL_BACK,
        callback_data=ProfileCancelCallback(action="back"),
    )
    builder.button(
        text=labels.CANCEL,
        callback_data=ProfileCancelCallback(action="cancel"),
    )
    builder.adjust(*([1] * len(page.items)), _season_navigation_width(page), 1, 1)
    return builder.as_markup()


def _season_navigation_width(page: Page) -> int:
    return 1 + int(page.has_previous) + int(page.has_next) if page.total_pages > 1 else 1
