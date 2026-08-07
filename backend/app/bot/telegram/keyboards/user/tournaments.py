from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.keyboards import labels
from app.services.dto.tournaments import TournamentView
from app.services.pagination import Page

TOURNAMENT_LIST_PAGE_SIZE = 6


class TournamentListAction(StrEnum):
    SELECT = "select"
    PAGE = "page"


class TournamentRegistrationCallback(CallbackData, prefix="tournament_register"):
    action: TournamentListAction
    page: int
    tournament_id: int


class TournamentCancellationCallback(CallbackData, prefix="tournament_cancel"):
    action: TournamentListAction
    page: int
    tournament_id: int


CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK = "tournament_registration:confirm"
CANCEL_TOURNAMENT_REGISTRATION_CALLBACK = "tournament_registration:cancel"
CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK = "tournament_cancellation:confirm"
CANCEL_TOURNAMENT_CANCELLATION_CALLBACK = "tournament_cancellation:cancel"


def tournament_registration_keyboard(
    page: Page[TournamentView],
    selected_tournament_ids: set[int] | None = None,
) -> InlineKeyboardMarkup:
    selected_tournament_ids = selected_tournament_ids or set()
    builder = InlineKeyboardBuilder()
    for tournament in page.items:
        prefix = labels.SELECTED_PREFIX if tournament.id in selected_tournament_ids else ""
        builder.button(
            text=f"{prefix}{tournament_fmt.label(tournament)}",
            callback_data=TournamentRegistrationCallback(
                action=TournamentListAction.SELECT,
                page=page.page,
                tournament_id=tournament.id,
            ),
        )
    _add_pagination_buttons(builder, page, TournamentRegistrationCallback)
    builder.button(
        text=labels.CONFIRM,
        callback_data=CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK,
    )
    builder.button(
        text=labels.CANCEL,
        callback_data=CANCEL_TOURNAMENT_REGISTRATION_CALLBACK,
    )
    _adjust_tournament_keyboard(builder, page)
    return builder.as_markup()


def tournament_cancellation_keyboard(
    page: Page[TournamentView],
    selected_tournament_ids: set[int] | None = None,
) -> InlineKeyboardMarkup:
    selected_tournament_ids = selected_tournament_ids or set()
    builder = InlineKeyboardBuilder()
    for tournament in page.items:
        prefix = labels.SELECTED_PREFIX if tournament.id in selected_tournament_ids else ""
        builder.button(
            text=f"{prefix}{tournament_fmt.label(tournament)}",
            callback_data=TournamentCancellationCallback(
                action=TournamentListAction.SELECT,
                page=page.page,
                tournament_id=tournament.id,
            ),
        )
    _add_pagination_buttons(builder, page, TournamentCancellationCallback)
    builder.button(
        text=labels.CONFIRM,
        callback_data=CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK,
    )
    builder.button(
        text=labels.CANCEL,
        callback_data=CANCEL_TOURNAMENT_CANCELLATION_CALLBACK,
    )
    _adjust_tournament_keyboard(builder, page)
    return builder.as_markup()


def _add_pagination_buttons(
    builder: InlineKeyboardBuilder,
    page: Page[TournamentView],
    callback_type: type[TournamentRegistrationCallback] | type[TournamentCancellationCallback],
) -> None:
    if page.total_pages <= 1:
        return
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=callback_type(
                action=TournamentListAction.PAGE,
                page=page.previous_page,
                tournament_id=0,
            ),
        )
    builder.button(
        text=_tournament_page_label(page),
        callback_data=callback_type(
            action=TournamentListAction.PAGE,
            page=page.page,
            tournament_id=0,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=callback_type(
                action=TournamentListAction.PAGE,
                page=page.next_page,
                tournament_id=0,
            ),
        )


def _adjust_tournament_keyboard(
    builder: InlineKeyboardBuilder,
    page: Page[TournamentView],
) -> None:
    item_rows = [1] * len(page.items)
    if page.total_pages > 1:
        navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
        builder.adjust(*item_rows, navigation_buttons, 2)
    else:
        builder.adjust(*item_rows, 2)


def _tournament_page_label(page: Page[TournamentView]) -> str:
    start = page.page * page.page_size + 1
    end = start + len(page.items) - 1
    return f"{start}-{end} из {page.total_items}"
