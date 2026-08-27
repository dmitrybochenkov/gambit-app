from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import _adjust_paged_keyboard


class SuperadminTournamentHubAction(StrEnum):
    CREATE = "create"
    OPEN = "open"
    CLOSED = "closed"
    BACK = "back"


class SuperadminTournamentHubCallback(CallbackData, prefix="superadmin_tournaments"):
    action: SuperadminTournamentHubAction


class SuperadminOpenTournamentAction(StrEnum):
    PAGE = "page"
    OPEN = "open"
    DELETE_PLAYER = "delete_player"
    CLOSE = "close"
    BACK_TO_HUB = "back_hub"
    BACK_TO_LIST = "back_list"


class SuperadminOpenTournamentCallback(CallbackData, prefix="superadmin_open_tours"):
    action: SuperadminOpenTournamentAction
    page: int = 0
    tournament_id: int = 0


def tournament_hub_keyboard(open_tournaments_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Создать",
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.CREATE),
    )
    builder.button(
        text=f"🔓 Открытые ({open_tournaments_count})",
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.OPEN),
    )
    builder.button(
        text="🔒 Закрытые",
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.CLOSED),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.BACK),
    )
    builder.adjust(1)
    return builder.as_markup()


def open_tournament_list_keyboard(page: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in page.items:
        builder.button(
            text=tournament_fmt.short_label(item.tournament),
            callback_data=SuperadminOpenTournamentCallback(
                action=SuperadminOpenTournamentAction.OPEN,
                page=page.page,
                tournament_id=item.tournament.id,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=SuperadminOpenTournamentCallback(
                    action=SuperadminOpenTournamentAction.PAGE,
                    page=page.previous_page,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=SuperadminOpenTournamentCallback(
                action=SuperadminOpenTournamentAction.PAGE,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=SuperadminOpenTournamentCallback(
                    action=SuperadminOpenTournamentAction.PAGE,
                    page=page.next_page,
                ),
            )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.BACK_TO_HUB,
            page=page.page,
        ),
    )
    _adjust_paged_keyboard(builder, page, item_rows=[1] * len(page.items))
    return builder.as_markup()


def open_tournament_card_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Удалить игрока",
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.DELETE_PLAYER,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_PANEL_CLOSE_TOURNAMENT,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.CLOSE,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminOpenTournamentCallback(
            action=SuperadminOpenTournamentAction.BACK_TO_LIST,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
