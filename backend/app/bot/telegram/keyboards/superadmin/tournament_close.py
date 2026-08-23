from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters import publications as publication_fmt
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import PLACE_EMOJIS, _adjust_paged_keyboard
from app.db.models.enums import TournamentCombinationType
from app.services.dto.results import TournamentResultPlayerView, TournamentResultsView
from app.services.dto.tournaments import TournamentView
from app.services.pagination import Page
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField


class AdminCloseTournamentAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    BACK = "back"
    CORRECTION_LIST = "correction"
    CLOSED_CORRECTION_LIST = "closed_correction"
    VIEW_PHOTOS = "view_photos"
    CONFIRM = "confirm"
    CHANGE_FUND = "change_fund"
    PUBLISH_PREVIEW = "publish_preview"
    PUBLISH_CONFIRM = "publish_confirm"
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
    PHOTOS = "photos"
    COMBINATIONS = "combinations"
    ADD_COMBINATION = "add_combination"
    SELECT_COMBINATION_PLAYER = "combination_player"
    SAVE_COMBINATION = "save_combination"
    DELETE_COMBINATION_MENU = "delete_combination_menu"
    DELETE_COMBINATION = "delete_combination"
    ADD_PHOTO = "add_photo"
    PHOTO_DONE = "photo_done"
    VIEW_PHOTOS = "view_photos"
    DELETE_PHOTOS_CONFIRM = "delete_photos_confirm"
    DELETE_PHOTOS = "delete_photos"
    CANCEL = "cancel"


class AdminTournamentRepairCallback(CallbackData, prefix="repair_tour"):
    action: AdminTournamentRepairAction
    tournament_id: int
    player_id: int = 0
    combination_id: int = 0
    combination_type: str = ""


class AdminClosedCorrectionAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    DATA = "data"
    FINISH = "finish"
    BACK = "back"
    CANCEL = "cancel"


class AdminClosedCorrectionCallback(CallbackData, prefix="closed_corr"):
    action: AdminClosedCorrectionAction
    tournament_id: int = 0
    page: int = 0


class AdminClosedResultPlayerAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    REPLACE = "replace"
    CANCEL = "cancel"


class AdminClosedResultPlayerCallback(CallbackData, prefix="closed_player"):
    action: AdminClosedResultPlayerAction
    tournament_id: int
    page: int
    player_id: int = 0


class AdminClosedResultField(StrEnum):
    KNOCKOUTS = "ko"
    BIG_KNOCKOUTS = "big"
    BONUS = "bonus"
    PLACE = "place"


class AdminClosedResultFieldAction(StrEnum):
    OPEN = "open"
    CANCEL = "cancel"


class AdminClosedResultFieldCallback(CallbackData, prefix="closed_field"):
    action: AdminClosedResultFieldAction
    tournament_id: int
    page: int
    player_id: int
    field: AdminClosedResultField


class AdminClosedResultValueAction(StrEnum):
    SET = "set"
    BACK = "back"
    CANCEL = "cancel"


class AdminClosedResultValueCallback(CallbackData, prefix="closed_value"):
    action: AdminClosedResultValueAction
    tournament_id: int
    page: int
    player_id: int
    field: AdminClosedResultField
    value: int = 0


class AdminClosedResultReplacementAction(StrEnum):
    CONFIRM = "confirm"
    APPLY = "apply"
    BACK = "back"
    CANCEL = "cancel"


class AdminClosedResultReplacementCallback(CallbackData, prefix="closed_replace"):
    action: AdminClosedResultReplacementAction
    tournament_id: int
    page: int
    current_player_id: int
    new_player_id: int = 0


def admin_close_tournament_list_keyboard(
    page: Page[object],
    *,
    has_correction_targets: bool = False,
    has_closed_correction_targets: bool = False,
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
    if has_correction_targets:
        builder.button(
            text="🛠 Корректировать турниры",
            callback_data=AdminCloseTournamentCallback(
                action=AdminCloseTournamentAction.CORRECTION_LIST,
                page=0,
            ),
        )
    if has_closed_correction_targets:
        builder.button(
            text="✏️ Править закрытый турнир",
            callback_data=AdminCloseTournamentCallback(
                action=AdminCloseTournamentAction.CLOSED_CORRECTION_LIST,
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
    if has_correction_targets:
        item_rows.append(1)
    if has_closed_correction_targets:
        item_rows.append(1)
    _adjust_paged_keyboard(builder, page, item_rows=item_rows)
    return builder.as_markup()


def admin_closed_correction_tournament_list_keyboard(
    page: Page[TournamentView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament in page.items:
        builder.button(
            text=(
                f"{tournament.date.day:02d}.{tournament.date.month:02d} — "
                f"{tournament.tournament_type_name or 'Неопределённый турнир'}"
            ),
            callback_data=AdminClosedCorrectionCallback(
                action=AdminClosedCorrectionAction.OPEN,
                tournament_id=tournament.id,
                page=page.page,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=AdminClosedCorrectionCallback(
                    action=AdminClosedCorrectionAction.PAGE,
                    page=page.previous_page,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=AdminClosedCorrectionCallback(
                action=AdminClosedCorrectionAction.PAGE,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=AdminClosedCorrectionCallback(
                    action=AdminClosedCorrectionAction.PAGE,
                    page=page.next_page,
                ),
            )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.BACK,
            page=0,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.CANCEL,
        ),
    )
    _adjust_paged_keyboard(builder, page, item_rows=[1] * len(page.items))
    return builder.as_markup()


def admin_closed_correction_card_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🏁 Внести данные",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.DATA,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text="✅ Завершить исправление",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.FINISH,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.PAGE,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_closed_result_players_keyboard(
    results: TournamentResultsView,
    page: Page[TournamentResultPlayerView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in page.items:
        builder.button(
            text=_closed_player_button_text(results, player),
            callback_data=AdminClosedResultPlayerCallback(
                action=AdminClosedResultPlayerAction.OPEN,
                tournament_id=results.tournament.id,
                page=page.page,
                player_id=player.player_id,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=AdminClosedResultPlayerCallback(
                    action=AdminClosedResultPlayerAction.PAGE,
                    tournament_id=results.tournament.id,
                    page=page.previous_page,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=AdminClosedResultPlayerCallback(
                action=AdminClosedResultPlayerAction.PAGE,
                tournament_id=results.tournament.id,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=AdminClosedResultPlayerCallback(
                    action=AdminClosedResultPlayerAction.PAGE,
                    tournament_id=results.tournament.id,
                    page=page.next_page,
                ),
            )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.OPEN,
            tournament_id=results.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.CANCEL,
            tournament_id=results.tournament.id,
            page=page.page,
        ),
    )
    _adjust_paged_keyboard(builder, page, item_rows=[1] * len(page.items))
    return builder.as_markup()


def admin_closed_result_player_fields_keyboard(
    results: TournamentResultsView,
    player: TournamentResultPlayerView,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field, text in [
        (AdminClosedResultField.KNOCKOUTS, "🥊 КО"),
        (AdminClosedResultField.BIG_KNOCKOUTS, "👑🥊 Босс КО"),
        (AdminClosedResultField.BONUS, f"➕ {results.bonus_points_label}"),
        (AdminClosedResultField.PLACE, "🏁 Место"),
    ]:
        if not is_result_field_allowed(
            field=ResultField(field.value),
            knockout_mode=results.knockout_mode,
            supports_bonus_points=results.supports_bonus_points,
        ):
            continue
        builder.button(
            text=text,
            callback_data=AdminClosedResultFieldCallback(
                action=AdminClosedResultFieldAction.OPEN,
                tournament_id=results.tournament.id,
                page=page,
                player_id=player.player_id,
                field=field,
            ),
        )
    builder.button(
        text="🔁 Заменить игрока",
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.REPLACE,
            tournament_id=results.tournament.id,
            page=page,
            player_id=player.player_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.PAGE,
            tournament_id=results.tournament.id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultFieldCallback(
            action=AdminClosedResultFieldAction.CANCEL,
            tournament_id=results.tournament.id,
            page=page,
            player_id=player.player_id,
            field=AdminClosedResultField.PLACE,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_closed_replacement_search_results_keyboard(
    *,
    tournament_id: int,
    page: int,
    current_player_id: int,
    players: list[object],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in players:
        builder.button(
            text=player.display_name,
            callback_data=AdminClosedResultReplacementCallback(
                action=AdminClosedResultReplacementAction.CONFIRM,
                tournament_id=tournament_id,
                page=page,
                current_player_id=current_player_id,
                new_player_id=player.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedResultReplacementCallback(
            action=AdminClosedResultReplacementAction.BACK,
            tournament_id=tournament_id,
            page=page,
            current_player_id=current_player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultReplacementCallback(
            action=AdminClosedResultReplacementAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
            current_player_id=current_player_id,
        ),
    )
    builder.adjust(*([1] * len(players)), 1, 1)
    return builder.as_markup()


def admin_closed_replacement_input_keyboard(
    *,
    tournament_id: int,
    page: int,
    current_player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedResultReplacementCallback(
            action=AdminClosedResultReplacementAction.BACK,
            tournament_id=tournament_id,
            page=page,
            current_player_id=current_player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultReplacementCallback(
            action=AdminClosedResultReplacementAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
            current_player_id=current_player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_closed_replacement_confirmation_keyboard(
    *,
    tournament_id: int,
    page: int,
    current_player_id: int,
    new_player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Заменить",
        callback_data=AdminClosedResultReplacementCallback(
            action=AdminClosedResultReplacementAction.APPLY,
            tournament_id=tournament_id,
            page=page,
            current_player_id=current_player_id,
            new_player_id=new_player_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedResultReplacementCallback(
            action=AdminClosedResultReplacementAction.BACK,
            tournament_id=tournament_id,
            page=page,
            current_player_id=current_player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultReplacementCallback(
            action=AdminClosedResultReplacementAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
            current_player_id=current_player_id,
            new_player_id=new_player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_closed_result_value_keyboard(
    *,
    tournament_id: int,
    page: int,
    player_id: int,
    field: AdminClosedResultField,
    occupied_places: set[int] | None = None,
    current_place: int | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    max_value = 5 if field == AdminClosedResultField.PLACE else 15
    occupied_places = occupied_places or set()
    for value in range(1, max_value + 1):
        builder.button(
            text=_closed_value_button_text(
                field=field,
                value=value,
                occupied_places=occupied_places,
                current_place=current_place,
            ),
            callback_data=AdminClosedResultValueCallback(
                action=AdminClosedResultValueAction.SET,
                tournament_id=tournament_id,
                page=page,
                player_id=player_id,
                field=field,
                value=value,
            ),
        )
    if field != AdminClosedResultField.PLACE:
        builder.button(
            text="🧹 Очистить",
            callback_data=AdminClosedResultValueCallback(
                action=AdminClosedResultValueAction.SET,
                tournament_id=tournament_id,
                page=page,
                player_id=player_id,
                field=field,
                value=0,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedResultValueCallback(
            action=AdminClosedResultValueAction.BACK,
            tournament_id=tournament_id,
            page=page,
            player_id=player_id,
            field=field,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultValueCallback(
            action=AdminClosedResultValueAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
            player_id=player_id,
            field=field,
        ),
    )
    value_rows = [5] if field == AdminClosedResultField.PLACE else [5, 5, 5]
    footer_rows = [1, 1] if field == AdminClosedResultField.PLACE else [1, 1, 1]
    builder.adjust(*value_rows, *footer_rows)
    return builder.as_markup()


def _closed_player_button_text(
    results: TournamentResultsView,
    player: TournamentResultPlayerView,
) -> str:
    parts = []
    if player.place is not None:
        parts.append(PLACE_EMOJIS.get(player.place, str(player.place)))
    if results.knockout_mode == "small_big" and player.big_knockouts_count > 0:
        parts.append(f"👑🥊 х{player.big_knockouts_count}")
    if results.knockout_mode in {"small", "small_big"} and player.knockouts_count > 0:
        parts.append(f"🥊 х{player.knockouts_count}")
    if results.supports_bonus_points and player.bonus_points > 0:
        parts.append(f"{results.bonus_points_label} {player.bonus_points}")
    return player.display_name if not parts else f"{player.display_name}: {' | '.join(parts)}"


def _closed_value_button_text(
    *,
    field: AdminClosedResultField,
    value: int,
    occupied_places: set[int],
    current_place: int | None,
) -> str:
    if field != AdminClosedResultField.PLACE:
        return str(value)
    if value == current_place:
        return f"✅ {value}"
    if value in occupied_places:
        return f"✔️ {value}"
    return str(value)


def admin_correction_tournament_list_keyboard(page: Page[object]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for readiness in page.items:
        tournament: TournamentView = readiness.tournament
        builder.button(
            text=f"{'✅' if readiness.is_ready else '⚠️'} "
            f"{tournament.date.day:02d}.{tournament.date.month:02d} — "
            f"{tournament.tournament_type_name or 'Неопределённый турнир'}",
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.OPEN,
                tournament_id=tournament.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.BACK,
            page=page.page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=0,
        ),
    )
    builder.adjust(*([1] * len(page.items)), 1, 1)
    return builder.as_markup()


def admin_correction_tournament_card_keyboard(readiness: object) -> InlineKeyboardMarkup:
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
        text="📸 Фотографии",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.PHOTOS,
            tournament_id=tournament.id,
        ),
    )
    builder.button(
        text="🃏 Комбинации вечера",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.COMBINATIONS,
            tournament_id=tournament.id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CORRECTION_LIST,
            page=0,
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
        text="⬅️ Назад",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.OPEN,
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
        text="⬅️ Назад",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_PLAYER,
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
    builder.adjust(*([1] * len(players)), 1, 1)
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
        text="⬅️ Назад",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_PLAYER,
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
        text="⬅️ Назад",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_PLAYER,
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


def admin_repair_photo_collect_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Готово",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.PHOTO_DONE,
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


def admin_repair_combination_root_keyboard(view: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Добавить",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_COMBINATION,
            tournament_id=view.tournament.id,
        ),
    )
    if view.combinations:
        builder.button(
            text="🗑 Удалить",
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.DELETE_COMBINATION_MENU,
                tournament_id=view.tournament.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.OPEN,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=view.tournament.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_repair_combination_players_keyboard(view: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in view.players:
        builder.button(
            text=player.display_name,
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.SELECT_COMBINATION_PLAYER,
                tournament_id=view.tournament.id,
                player_id=player.player_id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.COMBINATIONS,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=view.tournament.id,
        ),
    )
    builder.adjust(*([1] * len(view.players)), 1, 1)
    return builder.as_markup()


def admin_repair_combination_types_keyboard(
    *,
    tournament_id: int,
    player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for combination_type, text in [
        (TournamentCombinationType.FOUR_OF_A_KIND, "Каре"),
        (TournamentCombinationType.STRAIGHT_FLUSH, "Стрит-флеш"),
        (TournamentCombinationType.ROYAL_FLUSH, "Роял-флеш"),
    ]:
        builder.button(
            text=text,
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.SAVE_COMBINATION,
                tournament_id=tournament_id,
                player_id=player_id,
                combination_type=combination_type.value,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.ADD_COMBINATION,
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


def admin_repair_combination_delete_keyboard(view: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for combination in view.combinations:
        builder.button(
            text=(
                f"{combination.display_name} — "
                f"{publication_fmt.combination_label(combination.combination_type)}"
            ),
            callback_data=AdminTournamentRepairCallback(
                action=AdminTournamentRepairAction.DELETE_COMBINATION,
                tournament_id=view.tournament.id,
                combination_id=combination.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.COMBINATIONS,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminTournamentRepairCallback(
            action=AdminTournamentRepairAction.CANCEL,
            tournament_id=view.tournament.id,
        ),
    )
    builder.adjust(*([1] * len(view.combinations)), 1, 1)
    return builder.as_markup()


def admin_close_tournament_card_keyboard(*, tournament_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.BACK,
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


def admin_close_tournament_cancel_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.BACK,
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
        text="⬅️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.BACK,
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


def admin_publish_results_action_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📣 Опубликовать результаты",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.PUBLISH_PREVIEW,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text="❌ Закрыть",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_publish_results_preview_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Опубликовать",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.PUBLISH_CONFIRM,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
