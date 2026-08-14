from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import _adjust_paged_keyboard
from app.services.dto.hall_of_fame import HallOfFameCandidateView, HallOfFameSeasonListItemView
from app.services.pagination import Page

PAGE_SIZE = 5


class HallOfFameField(StrEnum):
    CHAMPION = "champion"
    KNOCKOUT = "knockout"


class HallOfFameSeasonAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class HallOfFameSeasonCallback(CallbackData, prefix="hof_season"):
    action: HallOfFameSeasonAction
    page: int = 0
    season_id: int = 0


class HallOfFameCardAction(StrEnum):
    CHOOSE_CHAMPION = "choose_champion"
    CHOOSE_KNOCKOUT = "choose_knockout"
    BACK = "back"
    CANCEL = "cancel"


class HallOfFameCardCallback(CallbackData, prefix="hof_card"):
    action: HallOfFameCardAction
    season_id: int
    page: int = 0


class HallOfFameSearchAction(StrEnum):
    OPEN = "open"
    BACK = "back"
    CANCEL = "cancel"


class HallOfFameSearchCallback(CallbackData, prefix="hof_search"):
    action: HallOfFameSearchAction
    season_id: int
    field: HallOfFameField
    player_id: int = 0


class HallOfFameConfirmAction(StrEnum):
    CONFIRM = "confirm"
    BACK = "back"
    CANCEL = "cancel"


class HallOfFameConfirmCallback(CallbackData, prefix="hof_confirm"):
    action: HallOfFameConfirmAction
    season_id: int
    field: HallOfFameField
    player_id: int


def seasons_keyboard(page: Page[HallOfFameSeasonListItemView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for season in page.items:
        builder.button(
            text=season.season_name,
            callback_data=HallOfFameSeasonCallback(
                action=HallOfFameSeasonAction.OPEN,
                page=page.page,
                season_id=season.season_id,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=HallOfFameSeasonCallback(
                    action=HallOfFameSeasonAction.PAGE,
                    page=page.previous_page,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=HallOfFameSeasonCallback(
                action=HallOfFameSeasonAction.PAGE,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=HallOfFameSeasonCallback(
                    action=HallOfFameSeasonAction.PAGE,
                    page=page.next_page,
                ),
            )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameSeasonCallback(
            action=HallOfFameSeasonAction.CANCEL,
            page=page.page,
        ),
    )
    _adjust_paged_keyboard(builder, page, item_rows=[1] * len(page.items), footer_rows=[1])
    return builder.as_markup()


def season_card_keyboard(*, season_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="💍 Выбрать чемпиона",
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.CHOOSE_CHAMPION,
            season_id=season_id,
            page=page,
        ),
    )
    builder.button(
        text="💥 Выбрать нокаутера",
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.CHOOSE_KNOCKOUT,
            season_id=season_id,
            page=page,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.BACK,
            season_id=season_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameCardCallback(
            action=HallOfFameCardAction.CANCEL,
            season_id=season_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def search_prompt_keyboard(*, season_id: int, field: HallOfFameField) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameSearchCallback(
            action=HallOfFameSearchAction.BACK,
            season_id=season_id,
            field=field,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameSearchCallback(
            action=HallOfFameSearchAction.CANCEL,
            season_id=season_id,
            field=field,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def search_results_keyboard(
    *,
    season_id: int,
    field: HallOfFameField,
    candidates: list[HallOfFameCandidateView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for candidate in candidates:
        builder.button(
            text=candidate.user.display_name,
            callback_data=HallOfFameSearchCallback(
                action=HallOfFameSearchAction.OPEN,
                season_id=season_id,
                field=field,
                player_id=candidate.user.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameSearchCallback(
            action=HallOfFameSearchAction.BACK,
            season_id=season_id,
            field=field,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameSearchCallback(
            action=HallOfFameSearchAction.CANCEL,
            season_id=season_id,
            field=field,
        ),
    )
    builder.adjust(*([1] * len(candidates)), 1, 1)
    return builder.as_markup()


def confirmation_keyboard(
    *,
    season_id: int,
    field: HallOfFameField,
    player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.CONFIRM,
        callback_data=HallOfFameConfirmCallback(
            action=HallOfFameConfirmAction.CONFIRM,
            season_id=season_id,
            field=field,
            player_id=player_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=HallOfFameConfirmCallback(
            action=HallOfFameConfirmAction.BACK,
            season_id=season_id,
            field=field,
            player_id=player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=HallOfFameConfirmCallback(
            action=HallOfFameConfirmAction.CANCEL,
            season_id=season_id,
            field=field,
            player_id=player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
