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
    PROBLEMATIC_LIST = "problematic"
    VIEW_PHOTOS = "view_photos"
    CONFIRM = "confirm"
    CHANGE_FUND = "change_fund"
    CANCEL = "cancel"


class AdminCloseTournamentCallback(CallbackData, prefix="close_tour"):
    action: AdminCloseTournamentAction
    page: int = 0
    tournament_id: int = 0


class AdminTournamentRepairAction(StrEnum):
    OPEN = "open"
    ADD_PLAYER = "add_player"
    ADD_EXISTING_SEARCH = "add_existing_search"
    ADD_NEW_PLAYER = "add_new_player"
    CONFIRM_EXISTING = "confirm_existing"
    ADD_EXISTING = "add_existing"
    CONFIRM_NEW = "confirm_new"
    CREATE_NEW = "create_new"
    EDIT_RESULTS = "edit_results"
    ADD_PHOTO = "add_photo"
    VIEW_PHOTOS = "view_photos"
    DELETE_PHOTOS = "delete_photos"
    CANCEL = "cancel"


class AdminTournamentRepairCallback(CallbackData, prefix="repair_tour"):
    action: AdminTournamentRepairAction
    tournament_id: int
    player_id: int = 0


def admin_close_tournament_list_keyboard(
    page: Page[object],
    *,
    has_problematic: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for readiness in page.items:
        if not readiness.is_ready:
            continue
        tournament: TournamentView = readiness.tournament
        builder.button(
            text=f"✅ {tournament.date.day:02d}.{tournament.date.month:02d} — "
            f"{tournament.tournament_type_name or 'Неопределённый турнир'}",
            callback_data=AdminCloseTournamentCallback(
                action=AdminCloseTournamentAction.OPEN,
                page=page.page,
                tournament_id=tournament.id,
            ),
        )
    if has_problematic:
        builder.button(
            text="🛠 Проблемные турниры",
            callback_data=AdminCloseTournamentCallback(
                action=AdminCloseTournamentAction.PROBLEMATIC_LIST,
                page=0,
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
    item_rows = [1] * len([item for item in page.items if item.is_ready])
    if has_problematic:
        item_rows.append(1)
    _adjust_paged_keyboard(builder, page, item_rows=item_rows)
    return builder.as_markup()


def admin_problematic_tournament_list_keyboard(page: Page[object]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for readiness in page.items:
        tournament: TournamentView = readiness.tournament
        builder.button(
            text=f"🛠 {tournament.date.day:02d}.{tournament.date.month:02d} — "
            f"{tournament.tournament_type_name or 'Неопределённый турнир'}",
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.OPEN,
                tournament_id=tournament.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=0,
        ),
    )
    builder.adjust(*([1] * len(page.items)), 1)
    return builder.as_markup()


def admin_problematic_tournament_card_keyboard(readiness: object) -> InlineKeyboardMarkup:
    tournament: TournamentView = readiness.tournament
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👤 Добавить игрока",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_PLAYER,
            tournament_id=tournament.id,
        ),
    )
    builder.button(
        text="🏁 Внести данные",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.EDIT_RESULTS,
            tournament_id=tournament.id,
        ),
    )
    builder.button(
        text="📸 Добавить фото",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_PHOTO,
            tournament_id=tournament.id,
        ),
    )
    if readiness.photo_count > 0:
        builder.button(
            text=f"🖼 Посмотреть фото ({readiness.photo_count})",
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.VIEW_PHOTOS,
                tournament_id=tournament.id,
            ),
        )
        builder.button(
            text="🗑 Удалить все фото",
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.DELETE_PHOTOS,
                tournament_id=tournament.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=tournament.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_repair_add_player_mode_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👤 Играл ранее",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_EXISTING_SEARCH,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text="🆕 Новый игрок",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_NEW_PLAYER,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_repair_search_results_keyboard(
    *,
    tournament_id: int,
    players: list[object],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in players:
        builder.button(
            text=player.display_name,
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.CONFIRM_EXISTING,
                tournament_id=tournament_id,
                player_id=player.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(*([1] * len(players)), 1)
    return builder.as_markup()


def admin_repair_add_existing_confirmation_keyboard(
    *,
    tournament_id: int,
    player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Добавить",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_EXISTING,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_repair_add_new_confirmation_keyboard(*, tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Создать",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CREATE_NEW,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
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
