from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import _adjust_paged_keyboard
from app.services.dto.tournaments import TournamentView
from app.services.pagination import Page


class AdminCloseTournamentAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    VIEW_PHOTOS = "view_photos"
    CONFIRM = "confirm"
    CHANGE_FUND = "change_fund"
    CANCEL = "cancel"


class AdminCloseTournamentCallback(CallbackData, prefix="close_tour"):
    action: AdminCloseTournamentAction
    page: int = 0
    tournament_id: int = 0


def admin_close_tournament_list_keyboard(page: Page[object]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for readiness in page.items:
        tournament: TournamentView = readiness.tournament
        marker = "✅" if readiness.is_ready else "⚠️"
        builder.button(
            text=f"{marker} {tournament.date.day:02d}.{tournament.date.month:02d} — "
            f"{tournament.tournament_type_name or 'Неопределённый турнир'}",
            callback_data=AdminCloseTournamentCallback(
                action=AdminCloseTournamentAction.OPEN,
                page=page.page,
                tournament_id=tournament.id,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=AdminCloseTournamentCallback(
                    action=AdminCloseTournamentAction.PAGE,
                    page=page.previous_page or 0,
                ),
            )
        builder.button(
            text=(
                f"{page.page * page.page_size + 1}-"
                f"{page.page * page.page_size + len(page.items)} из {page.total_items}"
            ),
            callback_data=AdminCloseTournamentCallback(
                action=AdminCloseTournamentAction.PAGE,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=AdminCloseTournamentCallback(
                    action=AdminCloseTournamentAction.PAGE,
                    page=page.next_page or page.page,
                ),
            )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CANCEL,
            page=page.page,
        ),
    )
    item_rows = [1] * len(page.items)
    _adjust_paged_keyboard(builder, page, item_rows=item_rows)
    return builder.as_markup()


def admin_close_tournament_card_keyboard(*, tournament_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CANCEL,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_close_tournament_cancel_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CANCEL,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_close_tournament_fund_error_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    return admin_close_tournament_cancel_keyboard(tournament_id=tournament_id, page=page)


def admin_close_tournament_confirmation_keyboard(
    *,
    tournament_id: int,
    page: int,
    photo_count: int = 0,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if photo_count > 0:
        builder.button(
            text=f"🖼 Посмотреть фото ({photo_count})",
            callback_data=AdminCloseTournamentCallback(
                action=AdminCloseTournamentAction.VIEW_PHOTOS,
                page=page,
                tournament_id=tournament_id,
            ),
        )
    builder.button(
        text="✅ Рассчитать и закрыть",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CONFIRM,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text="✏️ Изменить фонд",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CHANGE_FUND,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CANCEL,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
