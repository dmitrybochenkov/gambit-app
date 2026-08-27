from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import PLACE_EMOJIS, _adjust_paged_keyboard
from app.services.dto.results import TournamentResultPlayerView, TournamentResultsView
from app.services.dto.tournaments import TournamentView
from app.services.pagination import Page
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField


class AdminCloseTournamentAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    BACK = "back"
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


class AdminClosedCorrectionAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    PLAYERS = "players"
    DATA = "data"
    FUND = "fund"
    FUND_INPUT = "fund_input"
    FINISH = "finish"
    CONFIRM = "confirm"
    BACK_TO_HUB = "back_to_hub"
    BACK = "back"
    CANCEL = "cancel"


class AdminClosedCorrectionCallback(CallbackData, prefix="closed_corr"):
    action: AdminClosedCorrectionAction
    tournament_id: int = 0
    page: int = 0


class AdminClosedResultPlayerAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    ADD_SEARCH = "add_search"
    ADD_CONFIRM = "add_confirm"
    ADD_APPLY = "add_apply"
    DELETE_LIST = "delete_list"
    DELETE_PREVIEW = "delete_preview"
    DELETE_APPLY = "delete_apply"
    REPLACE = "replace"
    CANCEL = "cancel"


class AdminClosedResultPlayerCallback(CallbackData, prefix="closed_player"):
    action: AdminClosedResultPlayerAction
    tournament_id: int
    page: int
    player_id: int = 0
    target_player_id: int = 0


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


class AdminClosedFundAction(StrEnum):
    BACK = "back"
    CANCEL = "cancel"


class AdminClosedFundCallback(CallbackData, prefix="closed_fund"):
    action: AdminClosedFundAction
    tournament_id: int
    page: int


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


def admin_close_tournament_list_keyboard(page: Page[object]) -> InlineKeyboardMarkup:
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
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.BACK_TO_HUB,
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
        text="👥 Игроки",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.PLAYERS,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text="📊 Результаты",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.DATA,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text="💰 Фонд",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.FUND,
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


def admin_closed_correction_preview_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Применить исправления",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.CONFIRM,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text="✏️ Продолжить правки",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.OPEN,
            tournament_id=tournament_id,
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


def admin_closed_players_menu_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Добавить игрока",
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.ADD_SEARCH,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text="🗑 Удалить игрока",
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.DELETE_LIST,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.OPEN,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_closed_add_player_search_results_keyboard(
    *,
    tournament_id: int,
    page: int,
    players: list[object],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in players:
        builder.button(
            text=player.display_name,
            callback_data=AdminClosedResultPlayerCallback(
                action=AdminClosedResultPlayerAction.ADD_CONFIRM,
                tournament_id=tournament_id,
                page=page,
                target_player_id=player.id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.PLAYERS,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(*([1] * len(players)), 1, 1)
    return builder.as_markup()


def admin_closed_add_player_confirmation_keyboard(
    *,
    tournament_id: int,
    page: int,
    target_player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Добавить",
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.ADD_APPLY,
            tournament_id=tournament_id,
            page=page,
            target_player_id=target_player_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.ADD_SEARCH,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_closed_delete_player_list_keyboard(
    results: TournamentResultsView,
    *,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in results.players:
        builder.button(
            text=player.display_name,
            callback_data=AdminClosedResultPlayerCallback(
                action=AdminClosedResultPlayerAction.DELETE_PREVIEW,
                tournament_id=results.tournament.id,
                page=page,
                player_id=player.player_id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.PLAYERS,
            tournament_id=results.tournament.id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.CANCEL,
            tournament_id=results.tournament.id,
            page=page,
        ),
    )
    builder.adjust(*([1] * len(results.players)), 1, 1)
    return builder.as_markup()


def admin_closed_delete_player_confirmation_keyboard(
    *,
    tournament_id: int,
    page: int,
    player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Да, удалить",
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.DELETE_APPLY,
            tournament_id=tournament_id,
            page=page,
            player_id=player_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.DELETE_LIST,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedResultPlayerCallback(
            action=AdminClosedResultPlayerAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_closed_fund_keyboard(*, tournament_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Изменить фонд",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.FUND_INPUT,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedCorrectionCallback(
            action=AdminClosedCorrectionAction.OPEN,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedFundCallback(
            action=AdminClosedFundAction.CANCEL,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_closed_fund_input_keyboard(*, tournament_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminClosedFundCallback(
            action=AdminClosedFundAction.BACK,
            tournament_id=tournament_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminClosedFundCallback(
            action=AdminClosedFundAction.CANCEL,
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
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Закрыть турнир",
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
