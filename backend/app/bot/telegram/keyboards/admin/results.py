from enum import StrEnum
from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters import publications as publication_fmt
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import (
    PLACE_EMOJIS,
    _adjust_paged_keyboard,
    _admin_candidate_page_label,
)
from app.db.models.enums import TournamentCombinationType
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


class AdminResultBackToMenuCallback(CallbackData, prefix="res_back"):
    action: str = "admin_menu"


class AdminResultPlayerAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    ADD_PHOTO = "add_photo"
    VIEW_PHOTOS = "view_photos"
    DELETE_PHOTOS = "delete_photos"
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


class AdminResultPhotoAction(StrEnum):
    DONE = "done"
    VIEW = "view"
    DELETE_CONFIRM = "delete_confirm"
    DELETE_ALL = "delete_all"
    BACK = "back"
    CANCEL = "cancel"


class AdminResultPhotoCallback(CallbackData, prefix="res_photo"):
    action: AdminResultPhotoAction
    tournament_id: int


class AdminResultMenuAction(StrEnum):
    ROOT = "root"
    DATA = "data"
    PHOTOS = "photos"
    COMBINATIONS = "combinations"
    CANCEL = "cancel"


class AdminResultMenuCallback(CallbackData, prefix="res_menu"):
    action: AdminResultMenuAction
    tournament_id: int


class AdminCombinationAction(StrEnum):
    ADD = "add"
    DELETE_MENU = "delete_menu"
    SELECT_PLAYER = "player"
    SAVE = "save"
    DELETE = "delete"
    BACK = "back"
    CANCEL = "cancel"
    SELECT_RANK = "rank"


class AdminCombinationCallback(CallbackData, prefix="res_combo"):
    action: AdminCombinationAction
    tournament_id: int
    player_id: int = 0
    combination_id: int = 0
    combination_type: str = ""
    rank: str = ""


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


def admin_result_players_keyboard(
    results: TournamentResultsView,
    page: Page[TournamentResultPlayerView],
    *,
    back_callback: Any | None = None,
    cancel_callback: Any | None = None,
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
    if back_callback is not None:
        builder.button(
            text="⬅️ Назад",
            callback_data=back_callback,
        )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=cancel_callback
        or AdminResultPlayerCallback(
            action=AdminResultPlayerAction.CANCEL,
            tournament_id=results.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    item_rows = [1] * len(page.items)
    footer_rows = ([1] if back_callback is not None else []) + [1]
    _adjust_paged_keyboard(builder, page, item_rows=item_rows, footer_rows=footer_rows)
    return builder.as_markup()


def admin_result_root_keyboard(results: TournamentResultsView) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🏁 Внести данные",
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.DATA,
            tournament_id=results.tournament.id,
        ),
    )
    builder.button(
        text="📸 Фотографии",
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.PHOTOS,
            tournament_id=results.tournament.id,
        ),
    )
    builder.button(
        text="🃏 Комбинации вечера",
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.COMBINATIONS,
            tournament_id=results.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.CANCEL,
            tournament_id=results.tournament.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_combination_root_keyboard(view: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Добавить",
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.ADD,
            tournament_id=view.tournament.id,
        ),
    )
    if view.combinations:
        builder.button(
            text="🗑 Удалить",
            callback_data=AdminCombinationCallback(
                action=AdminCombinationAction.DELETE_MENU,
                tournament_id=view.tournament.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.ROOT,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.CANCEL,
            tournament_id=view.tournament.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_combination_players_keyboard(view: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in view.players:
        builder.button(
            text=player.display_name,
            callback_data=AdminCombinationCallback(
                action=AdminCombinationAction.SELECT_PLAYER,
                tournament_id=view.tournament.id,
                player_id=player.player_id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.BACK,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.CANCEL,
            tournament_id=view.tournament.id,
        ),
    )
    builder.adjust(*([1] * len(view.players)), 1, 1)
    return builder.as_markup()


def admin_combination_types_keyboard(*, tournament_id: int, player_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for combination_type, text in [
        (TournamentCombinationType.FOUR_OF_A_KIND, "Каре"),
        (TournamentCombinationType.STRAIGHT_FLUSH, "Стрит-флеш"),
        (TournamentCombinationType.ROYAL_FLUSH, "Роял-флеш"),
    ]:
        builder.button(
            text=text,
            callback_data=AdminCombinationCallback(
                action=(
                    AdminCombinationAction.SELECT_RANK
                    if combination_type == TournamentCombinationType.FOUR_OF_A_KIND
                    else AdminCombinationAction.SAVE
                ),
                tournament_id=tournament_id,
                player_id=player_id,
                combination_type=combination_type.value,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.ADD,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_four_of_a_kind_rank_keyboard(
    *,
    tournament_id: int,
    player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for rank in ("A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2"):
        builder.button(
            text=rank,
            callback_data=AdminCombinationCallback(
                action=AdminCombinationAction.SAVE,
                tournament_id=tournament_id,
                player_id=player_id,
                combination_type=TournamentCombinationType.FOUR_OF_A_KIND.value,
                rank=rank,
            ),
        )

    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.SELECT_PLAYER,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )

    builder.adjust(4, 4, 5, 1, 1)
    return builder.as_markup()


def admin_combination_delete_keyboard(view: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for combination in view.combinations:
        builder.button(
            text=(
                f"{combination.display_name} — "
                f"{publication_fmt.combination_label(combination.combination_type)}"
            ),
            callback_data=AdminCombinationCallback(
                action=AdminCombinationAction.DELETE,
                tournament_id=view.tournament.id,
                combination_id=combination.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.BACK,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCombinationCallback(
            action=AdminCombinationAction.CANCEL,
            tournament_id=view.tournament.id,
        ),
    )
    builder.adjust(*([1] * len(view.combinations)), 1, 1)
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
    builder.adjust(1)
    return builder.as_markup()


def admin_result_photo_menu_keyboard(
    results: TournamentResultsView,
    *,
    add_callback: Any | None = None,
    view_callback: Any | None = None,
    delete_callback: Any | None = None,
    back_callback: Any | None = None,
    cancel_callback: Any | None = None,
) -> InlineKeyboardMarkup:
    tournament_id = results.tournament.id
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📸 Добавить фото",
        callback_data=add_callback
        or AdminResultPlayerCallback(
            action=AdminResultPlayerAction.ADD_PHOTO,
            tournament_id=tournament_id,
            page=0,
            player_id=0,
        ),
    )
    if results.photo_count > 0:
        builder.button(
            text=f"🖼 Посмотреть фото ({results.photo_count})",
            callback_data=view_callback
            or AdminResultPlayerCallback(
                action=AdminResultPlayerAction.VIEW_PHOTOS,
                tournament_id=tournament_id,
                page=0,
                player_id=0,
            ),
        )
        builder.button(
            text="🗑 Удалить все фото",
            callback_data=delete_callback
            or AdminResultPlayerCallback(
                action=AdminResultPlayerAction.DELETE_PHOTOS,
                tournament_id=tournament_id,
                page=0,
                player_id=0,
            ),
        )
    if back_callback is not None:
        builder.button(text="⬅️ Назад", callback_data=back_callback)
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=cancel_callback
        or AdminResultPhotoCallback(
            action=AdminResultPhotoAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    footer_rows = [1]
    if results.photo_count > 0:
        footer_rows.extend([1, 1])
    if back_callback is not None:
        footer_rows.append(1)
    footer_rows.append(1)
    builder.adjust(*footer_rows)
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


def admin_result_delete_photos_confirmation_keyboard(
    tournament_id: int,
    *,
    back_callback: Any | None = None,
    cancel_callback: Any | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Удалить",
        callback_data=AdminResultPhotoCallback(
            action=AdminResultPhotoAction.DELETE_ALL,
            tournament_id=tournament_id,
        ),
    )
    if back_callback is not None:
        builder.button(text="⬅️ Назад", callback_data=back_callback)
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=cancel_callback
        or AdminResultPhotoCallback(
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
    *,
    back_callback: Any | None = None,
    cancel_callback: Any | None = None,
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
    if back_callback is not None:
        builder.button(text="⬅️ Назад", callback_data=back_callback)
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=cancel_callback
        or AdminResultFieldCallback(
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

    if field != AdminResultField.BONUS:
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
    if field == AdminResultField.PLACE:
        value_rows = [5]
    elif field == AdminResultField.BONUS:
        value_rows = []
    else:
        value_rows = [5, 5, 5]

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
