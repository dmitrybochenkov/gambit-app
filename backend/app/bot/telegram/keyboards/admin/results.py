from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import (
    PLACE_EMOJIS,
    _adjust_paged_keyboard,
    _admin_candidate_page_label,
)
from app.services.dto.results import TournamentResultPlayerView, TournamentResultsView
from app.services.dto.tournaments import TournamentView
from app.services.pagination import Page
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField

ADMIN_RESULT_PAGE_SIZE = 6


class AdminResultTournamentAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class AdminResultTournamentCallback(CallbackData, prefix="res_tour"):
    action: AdminResultTournamentAction
    page: int
    tournament_id: int


class AdminPastResultTournamentCallback(CallbackData, prefix="res_past"):
    action: AdminResultTournamentAction
    page: int
    tournament_id: int


class AdminResultBackToMenuCallback(CallbackData, prefix="res_back"):
    action: str = "admin_menu"


class AdminResultPlayerAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    ADD_EXISTING_SEARCH = "add_existing_search"
    ADD_NEW_PLAYER = "add_new_player"
    ADD_PHOTO = "add_photo"
    VIEW_PHOTOS = "view_photos"
    DELETE_PHOTOS = "delete_photos"
    PAST_TOURNAMENTS = "past_tournaments"
    CANCEL = "cancel"


class AdminResultPlayerCallback(CallbackData, prefix="res_player"):
    action: AdminResultPlayerAction
    tournament_id: int
    page: int
    player_id: int


class AdminResultField(StrEnum):
    KNOCKOUTS = "ko"
    BIG_KNOCKOUTS = "big"
    BONUS = "bonus"
    PLACE = "place"


class AdminResultFieldAction(StrEnum):
    OPEN = "open"
    CANCEL = "cancel"


class AdminResultFieldCallback(CallbackData, prefix="res_field"):
    action: AdminResultFieldAction
    tournament_id: int
    page: int
    player_id: int
    field: AdminResultField


class AdminResultValueAction(StrEnum):
    SET = "set"
    MANUAL = "manual"
    BACK = "back"
    CANCEL = "cancel"


class AdminResultValueCallback(CallbackData, prefix="res_value"):
    action: AdminResultValueAction
    tournament_id: int
    page: int
    player_id: int
    field: AdminResultField
    value: int


class AdminResultAddPlayerAction(StrEnum):
    CONFIRM_EXISTING = "confirm_existing"
    ADD_EXISTING = "add_existing"
    CONFIRM_NEW = "confirm_new"
    CREATE_NEW = "create_new"
    CANCEL = "cancel"


class AdminResultAddPlayerCallback(CallbackData, prefix="res_add"):
    action: AdminResultAddPlayerAction
    tournament_id: int
    player_id: int = 0


class AdminResultPhotoAction(StrEnum):
    DONE = "done"
    VIEW = "view"
    DELETE_CONFIRM = "delete_confirm"
    DELETE_ALL = "delete_all"
    CANCEL = "cancel"


class AdminResultPhotoCallback(CallbackData, prefix="res_photo"):
    action: AdminResultPhotoAction
    tournament_id: int


def admin_result_tournament_list_keyboard(
    page: Page[TournamentView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament in page.items:
        builder.button(
            text=str(tournament.id),
            callback_data=AdminResultTournamentCallback(
                action=AdminResultTournamentAction.OPEN,
                page=page.page,
                tournament_id=tournament.id,
            ),
        )
    _add_result_tournament_page_buttons(builder, page)
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultTournamentCallback(
            action=AdminResultTournamentAction.CANCEL,
            page=page.page,
            tournament_id=0,
        ),
    )
    item_rows = [3] * (len(page.items) // 3)
    if len(page.items) % 3:
        item_rows.append(len(page.items) % 3)
    _adjust_paged_keyboard(builder, page, item_rows=item_rows)
    return builder.as_markup()


def admin_past_result_tournament_list_keyboard(
    page: Page[TournamentView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament in page.items:
        builder.button(
            text=str(tournament.id),
            callback_data=AdminPastResultTournamentCallback(
                action=AdminResultTournamentAction.OPEN,
                page=page.page,
                tournament_id=tournament.id,
            ),
        )
    _add_past_result_tournament_page_buttons(builder, page)
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminPastResultTournamentCallback(
            action=AdminResultTournamentAction.CANCEL,
            page=page.page,
            tournament_id=0,
        ),
    )
    item_rows = [3] * (len(page.items) // 3)
    if len(page.items) % 3:
        item_rows.append(len(page.items) % 3)
    _adjust_paged_keyboard(builder, page, item_rows=item_rows)
    return builder.as_markup()


def admin_result_players_keyboard(
    results: TournamentResultsView,
    page: Page[TournamentResultPlayerView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in page.items:
        builder.button(
            text=_admin_result_player_button_text(results, player),
            callback_data=AdminResultPlayerCallback(
                action=AdminResultPlayerAction.OPEN,
                tournament_id=results.tournament.id,
                page=page.page,
                player_id=player.player_id,
            ),
        )
    _add_result_player_page_buttons(builder, page, results.tournament.id)
    builder.button(
        text="👤 Играл ранее",
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.ADD_EXISTING_SEARCH,
            tournament_id=results.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    builder.button(
        text="🆕 Новый игрок",
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.ADD_NEW_PLAYER,
            tournament_id=results.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    builder.button(
        text="📸 Добавить фото",
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.ADD_PHOTO,
            tournament_id=results.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    if results.photo_count > 0:
        builder.button(
            text=f"🖼 Посмотреть фото ({results.photo_count})",
            callback_data=AdminResultPlayerCallback(
                action=AdminResultPlayerAction.VIEW_PHOTOS,
                tournament_id=results.tournament.id,
                page=page.page,
                player_id=0,
            ),
        )
        builder.button(
            text="🗑 Удалить все фото",
            callback_data=AdminResultPlayerCallback(
                action=AdminResultPlayerAction.DELETE_PHOTOS,
                tournament_id=results.tournament.id,
                page=page.page,
                player_id=0,
            ),
        )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.CANCEL,
            tournament_id=results.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    builder.button(
        text="⌛ Прошедший турнир",
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.PAST_TOURNAMENTS,
            tournament_id=results.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    item_rows = [1] * len(page.items)
    footer_rows = [1, 1, 1] + ([1, 1] if results.photo_count > 0 else []) + [1, 1]
    _adjust_paged_keyboard(builder, page, item_rows=item_rows, footer_rows=footer_rows)
    return builder.as_markup()


def admin_result_root_no_today_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.CANCEL,
            tournament_id=0,
            page=0,
            player_id=0,
        ),
    )
    builder.button(
        text="⌛ Прошедший турнир",
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.PAST_TOURNAMENTS,
            tournament_id=0,
            page=0,
            player_id=0,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_search_results_keyboard(
    *,
    tournament_id: int,
    players: list[object],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in players:
        builder.button(
            text=player.display_name,
            callback_data=AdminResultAddPlayerCallback(
                action=AdminResultAddPlayerAction.CONFIRM_EXISTING,
                tournament_id=tournament_id,
                player_id=player.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultAddPlayerCallback(
            action=AdminResultAddPlayerAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(*([1] * len(players)), 1)
    return builder.as_markup()


def admin_result_add_existing_confirmation_keyboard(
    *,
    tournament_id: int,
    player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Добавить",
        callback_data=AdminResultAddPlayerCallback(
            action=AdminResultAddPlayerAction.ADD_EXISTING,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultAddPlayerCallback(
            action=AdminResultAddPlayerAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_add_new_confirmation_keyboard(*, tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Создать",
        callback_data=AdminResultAddPlayerCallback(
            action=AdminResultAddPlayerAction.CREATE_NEW,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultAddPlayerCallback(
            action=AdminResultAddPlayerAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_add_player_cancel_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultAddPlayerCallback(
            action=AdminResultAddPlayerAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_photo_collect_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Готово",
        callback_data=AdminResultPhotoCallback(
            action=AdminResultPhotoAction.DONE,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultPhotoCallback(
            action=AdminResultPhotoAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_delete_photos_confirmation_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Удалить",
        callback_data=AdminResultPhotoCallback(
            action=AdminResultPhotoAction.DELETE_ALL,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultPhotoCallback(
            action=AdminResultPhotoAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def _admin_result_player_button_text(
    results: TournamentResultsView,
    player: TournamentResultPlayerView,
) -> str:
    result_parts = []
    if player.place is not None:
        result_parts.append(PLACE_EMOJIS.get(player.place, str(player.place)))
    if results.knockout_mode == "small_big" and player.big_knockouts_count > 0:
        result_parts.append(f"👑🥊 х{player.big_knockouts_count}")
    if results.knockout_mode in {"small", "small_big"} and player.knockouts_count > 0:
        result_parts.append(f"🥊 х{player.knockouts_count}")
    if results.supports_bonus_points and player.bonus_points > 0:
        result_parts.append(f"{results.bonus_points_label} {player.bonus_points}")
    if not result_parts:
        return player.display_name
    return f"{player.display_name}: {' | '.join(result_parts)}"


def admin_result_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="↩️ В админское меню",
        callback_data=AdminResultBackToMenuCallback(),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_player_fields_keyboard(
    results: TournamentResultsView,
    player: TournamentResultPlayerView,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field, text in [
        (AdminResultField.KNOCKOUTS, "🥊 КО"),
        (AdminResultField.BIG_KNOCKOUTS, "👑🥊 Босс КО"),
        (AdminResultField.BONUS, f"➕ {results.bonus_points_label}"),
        (AdminResultField.PLACE, "🏁 Место"),
    ]:
        if not is_result_field_allowed(
            field=ResultField(field.value),
            knockout_mode=results.knockout_mode,
            supports_bonus_points=results.supports_bonus_points,
        ):
            continue
        builder.button(
            text=text,
            callback_data=AdminResultFieldCallback(
                action=AdminResultFieldAction.OPEN,
                tournament_id=results.tournament.id,
                page=page,
                player_id=player.player_id,
                field=field,
            ),
        )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultFieldCallback(
            action=AdminResultFieldAction.CANCEL,
            tournament_id=results.tournament.id,
            page=page,
            player_id=player.player_id,
            field=AdminResultField.PLACE,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_value_keyboard(
    *,
    tournament_id: int,
    page: int,
    player_id: int,
    field: AdminResultField,
    occupied_places: set[int] | None = None,
    current_place: int | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    max_value = 5 if field == AdminResultField.PLACE else 15
    occupied_places = occupied_places or set()
    for value in range(1, max_value + 1):
        text = _admin_result_value_button_text(
            field=field,
            value=value,
            occupied_places=occupied_places,
            current_place=current_place,
        )
        builder.button(
            text=text,
            callback_data=AdminResultValueCallback(
                action=AdminResultValueAction.SET,
                tournament_id=tournament_id,
                page=page,
                player_id=player_id,
                field=field,
                value=value,
            ),
        )
    footer_rows = []
    if field != AdminResultField.PLACE:
        if field == AdminResultField.BONUS:
            builder.button(
                text="🧹 Очистить",
                callback_data=AdminResultValueCallback(
                    action=AdminResultValueAction.SET,
                    tournament_id=tournament_id,
                    page=page,
                    player_id=player_id,
                    field=field,
                    value=0,
                ),
            )
            footer_rows.append(1)
        builder.button(
            text="⌨️ Ввести руками",
            callback_data=AdminResultValueCallback(
                action=AdminResultValueAction.MANUAL,
                tournament_id=tournament_id,
                page=page,
                player_id=player_id,
                field=field,
                value=0,
            ),
        )
        footer_rows.append(1)
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminResultValueCallback(
            action=AdminResultValueAction.BACK,
            tournament_id=tournament_id,
            page=page,
            player_id=player_id,
            field=field,
            value=0,
        ),
    )
    footer_rows.append(1)
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultValueCallback(
            action=AdminResultValueAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
            player_id=player_id,
            field=field,
            value=0,
        ),
    )
    footer_rows.append(1)
    value_rows = [5] if field == AdminResultField.PLACE else [5, 5, 5]
    builder.adjust(*value_rows, *footer_rows)
    return builder.as_markup()


def _admin_result_value_button_text(
    *,
    field: AdminResultField,
    value: int,
    occupied_places: set[int],
    current_place: int | None,
) -> str:
    if field != AdminResultField.PLACE:
        return str(value)
    if value == current_place:
        return f"✅ {value}"
    if value in occupied_places:
        return f"✔️ {value}"
    return str(value)


def admin_result_manual_value_keyboard(
    *,
    tournament_id: int,
    page: int,
    player_id: int,
    field: AdminResultField,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminResultValueCallback(
            action=AdminResultValueAction.BACK,
            tournament_id=tournament_id,
            page=page,
            player_id=player_id,
            field=field,
            value=0,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultValueCallback(
            action=AdminResultValueAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
            player_id=player_id,
            field=field,
            value=0,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def _add_result_tournament_page_buttons(
    builder: InlineKeyboardBuilder,
    page: Page[TournamentView],
) -> None:
    if page.total_pages <= 1:
        return
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=AdminResultTournamentCallback(
                action=AdminResultTournamentAction.PAGE,
                page=page.previous_page,
                tournament_id=0,
            ),
        )


def _add_past_result_tournament_page_buttons(
    builder: InlineKeyboardBuilder,
    page: Page[TournamentView],
) -> None:
    if page.total_pages <= 1:
        return
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=AdminPastResultTournamentCallback(
                action=AdminResultTournamentAction.PAGE,
                page=page.previous_page,
                tournament_id=0,
            ),
        )
    builder.button(
        text=_admin_candidate_page_label(page),
        callback_data=AdminPastResultTournamentCallback(
            action=AdminResultTournamentAction.PAGE,
            page=page.page,
            tournament_id=0,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=AdminPastResultTournamentCallback(
                action=AdminResultTournamentAction.PAGE,
                page=page.next_page,
                tournament_id=0,
            ),
        )
    builder.button(
        text=_admin_candidate_page_label(page),
        callback_data=AdminResultTournamentCallback(
            action=AdminResultTournamentAction.PAGE,
            page=page.page,
            tournament_id=0,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=AdminResultTournamentCallback(
                action=AdminResultTournamentAction.PAGE,
                page=page.next_page,
                tournament_id=0,
            ),
        )


def _add_result_player_page_buttons(
    builder: InlineKeyboardBuilder,
    page: Page[TournamentResultPlayerView],
    tournament_id: int,
) -> None:
    if page.total_pages <= 1:
        return
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=AdminResultPlayerCallback(
                action=AdminResultPlayerAction.PAGE,
                tournament_id=tournament_id,
                page=page.previous_page,
                player_id=0,
            ),
        )
    builder.button(
        text=_admin_candidate_page_label(page),
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.PAGE,
            tournament_id=tournament_id,
            page=page.page,
            player_id=0,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=AdminResultPlayerCallback(
                action=AdminResultPlayerAction.PAGE,
                tournament_id=tournament_id,
                page=page.next_page,
                player_id=0,
            ),
        )
