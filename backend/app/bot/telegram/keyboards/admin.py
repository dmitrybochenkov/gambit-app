from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram import texts
from app.bot.telegram.keyboards import buttons
from app.services.dto import (
    CheckInCandidateView,
    RegistrationCandidateView,
    RegistrationReviewView,
    TournamentCheckInView,
    TournamentPromptDayEditView,
    TournamentPromptView,
    TournamentResultPlayerView,
    TournamentResultsView,
    TournamentView,
    UserView,
)
from app.services.pagination import Page
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField

REGISTRATION_LIST_PAGE_SIZE = 6
ADMIN_CANDIDATE_PAGE_SIZE = 6
ADMIN_RESULT_PAGE_SIZE = 6
ADMIN_CHECK_IN_PAGE_SIZE = 6
PLACE_EMOJIS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
}


class RegistrationReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    EDIT_NAME = "edit_name"
    SELECT_CANDIDATE = "select_candidate"


class RegistrationReviewCallback(CallbackData, prefix="registration_review"):
    action: RegistrationReviewAction
    request_id: int


class RegistrationCandidateSelectionCallback(CallbackData, prefix="registration_candidate"):
    request_id: int
    user_id: int


class RegistrationListAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class RegistrationListCallback(CallbackData, prefix="registration_list"):
    action: RegistrationListAction
    page: int
    request_id: int


class CalendarPromptAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    EDIT = "edit"
    BACK = "back"


class CalendarPromptCallback(CallbackData, prefix="calendar_prompt"):
    action: CalendarPromptAction
    prompt_id: int


class AdminCalendarAction(StrEnum):
    SEASONS = "seasons"
    TOURNAMENTS = "tournaments"
    CANCEL = "cancel"


class AdminCalendarCallback(CallbackData, prefix="admin_calendar"):
    action: AdminCalendarAction


class SeasonOpenAction(StrEnum):
    CONFIRM = "confirm"
    CHANGE = "change"
    NAME = "name"
    STARTS_AT = "starts_at"
    BACK = "back"
    CANCEL = "cancel"


class SeasonOpenCallback(CallbackData, prefix="season_open"):
    action: SeasonOpenAction
    prompt_id: int


class AdminCandidateAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class AdminCandidateCallback(CallbackData, prefix="admin_candidate"):
    action: AdminCandidateAction
    page: int
    player_id: int


class AdminAddAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"


class AdminAddCallback(CallbackData, prefix="admin_add"):
    action: AdminAddAction
    player_id: int


class AdminResultTournamentAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class AdminResultTournamentCallback(CallbackData, prefix="res_tour"):
    action: AdminResultTournamentAction
    page: int
    tournament_id: int


class AdminResultMenuAction(StrEnum):
    PLAYERS = "players"
    CANCEL = "cancel"


class AdminResultMenuCallback(CallbackData, prefix="res_menu"):
    action: AdminResultMenuAction
    tournament_id: int


class AdminCloseTournamentAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    ENTER_FUND = "enter_fund"
    CONFIRM = "confirm"
    CHANGE_FUND = "change_fund"
    BACK = "back"
    CANCEL = "cancel"


class AdminCloseTournamentCallback(CallbackData, prefix="close_tour"):
    action: AdminCloseTournamentAction
    page: int = 0
    tournament_id: int = 0


class AdminResultPlayerAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    BACK = "back"
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


class AdminCheckInAction(StrEnum):
    CONFIRM_REGISTERED = "confirm_registered"
    ADD_REGISTERED = "add_registered"
    REGISTERED_SEARCH = "registered_search"
    DATABASE_SEARCH = "database_search"
    CONFIRM_EXISTING = "confirm_existing"
    ADD_EXISTING = "add_existing"
    NEW_PLAYER = "new_player"
    CONFIRM_NEW = "confirm_new"
    CREATE_NEW = "create_new"
    CHOOSE_OTHER_NEW = "choose_other_new"
    BACK = "back"
    BACK_TO_TOURNAMENT = "back_to_tournament"
    CANCEL = "cancel"


class AdminCheckInCallback(CallbackData, prefix="check_in"):
    action: AdminCheckInAction
    tournament_id: int
    page: int = 0
    player_id: int = 0


class TournamentPromptDayEditCallback(CallbackData, prefix="tour_prompt_day"):
    prompt_id: int
    tournament_date: str


class TournamentTypeEditCallback(CallbackData, prefix="tournament_type_edit"):
    prompt_id: int
    tournament_date: str
    tournament_type_id: int


def registration_review_keyboard(
    request_id: int,
    can_edit_name: bool = False,
    can_select_candidate: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_select_candidate:
        builder.button(
            text="🔗 Выбрать игрока",
            callback_data=RegistrationReviewCallback(
                action=RegistrationReviewAction.SELECT_CANDIDATE,
                request_id=request_id,
            ),
        )
    if can_edit_name:
        builder.button(
            text="✏️ Изменить имя",
            callback_data=RegistrationReviewCallback(
                action=RegistrationReviewAction.EDIT_NAME,
                request_id=request_id,
            ),
        )
    builder.button(
        text=buttons.ADMIN_APPROVE,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.APPROVE,
            request_id=request_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_REJECT,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            request_id=request_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            request_id=request_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_panel_keyboard(admin: UserView) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=buttons.ADMIN_PANEL_CHECK_IN)],
        [KeyboardButton(text=buttons.ADMIN_PANEL_RESULTS)],
        [KeyboardButton(text=buttons.ADMIN_PANEL_SUPERADMIN)],
    ]
    keyboard.append([KeyboardButton(text=buttons.ADMIN_PANEL_EXIT)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def superadmin_panel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=buttons.ADMIN_PANEL_REGISTRATIONS)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_CALENDAR)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_ADD_ADMIN)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_CLOSE_TOURNAMENT)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_BACK)],
        ],
        resize_keyboard=True,
    )


def registration_list_keyboard(page: Page[RegistrationReviewView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for review in page.items:
        builder.button(
            text=str(review.request.id),
            callback_data=RegistrationListCallback(
                action=RegistrationListAction.OPEN,
                page=page.page,
                request_id=review.request.id,
            ),
        )

    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=RegistrationListCallback(
                    action=RegistrationListAction.PAGE,
                    page=page.previous_page,
                    request_id=0,
                ),
            )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=RegistrationListCallback(
                    action=RegistrationListAction.PAGE,
                    page=page.next_page,
                    request_id=0,
                ),
            )

    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=RegistrationListCallback(
            action=RegistrationListAction.CANCEL,
            page=page.page,
            request_id=0,
        ),
    )

    id_rows = [3] * (len(page.items) // 3)
    if len(page.items) % 3:
        id_rows.append(len(page.items) % 3)
    if page.total_pages > 1:
        arrows_count = int(page.has_previous) + int(page.has_next)
        builder.adjust(*id_rows, arrows_count, 1)
    else:
        builder.adjust(*id_rows, 1)
    return builder.as_markup()


def admin_candidate_list_keyboard(page: Page[UserView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in page.items:
        builder.button(
            text=f"{player.id}. {player.display_name}",
            callback_data=AdminCandidateCallback(
                action=AdminCandidateAction.OPEN,
                page=page.page,
                player_id=player.id,
            ),
        )

    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=AdminCandidateCallback(
                    action=AdminCandidateAction.PAGE,
                    page=page.previous_page,
                    player_id=0,
                ),
            )
        builder.button(
            text=_admin_candidate_page_label(page),
            callback_data=AdminCandidateCallback(
                action=AdminCandidateAction.PAGE,
                page=page.page,
                player_id=0,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=AdminCandidateCallback(
                    action=AdminCandidateAction.PAGE,
                    page=page.next_page,
                    player_id=0,
                ),
            )

    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCandidateCallback(
            action=AdminCandidateAction.CANCEL,
            page=page.page,
            player_id=0,
        ),
    )

    item_rows = [1] * len(page.items)
    if page.total_pages > 1:
        navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
        builder.adjust(*item_rows, navigation_buttons, 1)
    else:
        builder.adjust(*item_rows, 1)
    return builder.as_markup()


def admin_add_confirmation_keyboard(player_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_ADD_CONFIRM,
        callback_data=AdminAddCallback(
            action=AdminAddAction.CONFIRM,
            player_id=player_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminAddCallback(
            action=AdminAddAction.CANCEL,
            player_id=player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


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
        text=buttons.ADMIN_CANCEL,
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


def admin_close_tournament_list_keyboard(page: Page[TournamentView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament in page.items:
        builder.button(
            text=f"{tournament.date.day:02d}.{tournament.date.month:02d} — "
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
        text=buttons.ADMIN_CANCEL,
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
        text="↩️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.BACK,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
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
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔄 Ввести снова",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.ENTER_FUND,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.BACK,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CANCEL,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_close_tournament_confirmation_keyboard(
    *,
    tournament_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
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
        text="↩️ Назад",
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.BACK,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCloseTournamentCallback(
            action=AdminCloseTournamentAction.CANCEL,
            page=page,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_menu_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_RESULTS_PLAYERS,
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.PLAYERS,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_keyboard(
    view: TournamentCheckInView,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Зарегистрированный",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.REGISTERED_SEARCH,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text="👤 Незарегистрированный, но играл ранее",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.DATABASE_SEARCH,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text="🆕 Незарегистрированный, новый",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.NEW_PLAYER,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=view.tournament.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_search_results_keyboard(
    *,
    tournament_id: int,
    players: list[CheckInCandidateView] | list[UserView],
    action: AdminCheckInAction,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in players:
        is_check_in_player = isinstance(player, CheckInCandidateView)
        user_id = player.user_id if is_check_in_player else player.id
        display_name = player.display_name
        marker = "☑️ " if is_check_in_player and player.is_checked_in else ""
        builder.button(
            text=f"{marker}{display_name}",
            callback_data=AdminCheckInCallback(
                action=action,
                tournament_id=tournament_id,
                player_id=user_id,
            ),
        )
    builder.button(
        text="↩️ Назад",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.BACK_TO_TOURNAMENT,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(*([1] * len(players)), 1, 1)
    return builder.as_markup()


def admin_check_in_similar_players_keyboard(
    *,
    tournament_id: int,
    players: list[UserView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in players:
        builder.button(
            text=player.display_name,
            callback_data=AdminCheckInCallback(
                action=AdminCheckInAction.CONFIRM_EXISTING,
                tournament_id=tournament_id,
                player_id=player.id,
            ),
        )
    builder.button(
        text="🆕 Это другой игрок",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CONFIRM_NEW,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.NEW_PLAYER,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(*([1] * len(players)), 1, 1, 1)
    return builder.as_markup()


def admin_check_in_exact_match_keyboard(
    *,
    tournament_id: int,
    user_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👤 Выбрать существующего",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CONFIRM_EXISTING,
            tournament_id=tournament_id,
            player_id=user_id,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.NEW_PLAYER,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_confirmation_keyboard(
    *,
    tournament_id: int,
    player_id: int = 0,
    confirm_action: AdminCheckInAction,
    confirm_text: str = "✅ Подтвердить",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=confirm_text,
        callback_data=AdminCheckInCallback(
            action=confirm_action,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.BACK,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_cancel_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_empty_search_keyboard(
    *,
    tournament_id: int,
    search_action: AdminCheckInAction,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔍 Искать снова",
        callback_data=AdminCheckInCallback(
            action=search_action,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.BACK_TO_TOURNAMENT,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
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
        text="⬅️ Назад",
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.BACK,
            tournament_id=results.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.CANCEL,
            tournament_id=results.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    item_rows = [1] * len(page.items)
    footer_rows = [1, 1, 1]
    _adjust_paged_keyboard(builder, page, item_rows=item_rows, footer_rows=footer_rows)
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
        result_parts.append(f"Бонус {player.bonus_points}")
    if not result_parts:
        return player.display_name
    return f"{player.display_name}: {' | '.join(result_parts)}"


def admin_result_cancel_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    return builder.as_markup()


def admin_result_player_fields_keyboard(
    results: TournamentResultsView,
    player: TournamentResultPlayerView,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field, text in [
        (AdminResultField.KNOCKOUTS, "🥊 КО"),
        (AdminResultField.BIG_KNOCKOUTS, "👑🥊 Большие КО"),
        (AdminResultField.BONUS, "🎁 Бонус"),
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
        text=buttons.ADMIN_CANCEL,
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
        text=buttons.ADMIN_CANCEL,
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
        text=buttons.ADMIN_CANCEL,
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


def _admin_candidate_page_label(page: Page[UserView]) -> str:
    start = page.page * page.page_size + 1
    end = start + len(page.items) - 1
    return f"{start}-{end} из {page.total_items}"


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


def _add_check_in_page_buttons(
    builder: InlineKeyboardBuilder,
    page: Page[CheckInCandidateView],
    tournament_id: int,
) -> None:
    if page.total_pages <= 1:
        return
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=AdminCheckInCallback(
                action=AdminCheckInAction.BACK,
                tournament_id=tournament_id,
                page=page.previous_page,
            ),
        )
    builder.button(
        text=_admin_candidate_page_label(page),
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.BACK,
            tournament_id=tournament_id,
            page=page.page,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=AdminCheckInCallback(
                action=AdminCheckInAction.BACK,
                tournament_id=tournament_id,
                page=page.next_page,
            ),
        )


def _adjust_paged_keyboard(
    builder: InlineKeyboardBuilder,
    page: Page,
    item_rows: list[int],
    footer_rows: list[int] | None = None,
) -> None:
    footer_rows = footer_rows or [1]
    if page.total_pages > 1:
        navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
        builder.adjust(*item_rows, navigation_buttons, *footer_rows)
    else:
        builder.adjust(*item_rows, *footer_rows)


def registration_candidate_selection_keyboard(
    request_id: int,
    candidates: list[RegistrationCandidateView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for position, candidate in enumerate(candidates, start=1):
        builder.button(
            text=(f"{position}. {candidate.user.display_name} ({candidate.score}%)"),
            callback_data=RegistrationCandidateSelectionCallback(
                request_id=request_id,
                user_id=candidate.user.id,
            ),
        )
    builder.button(
        text=buttons.ADMIN_APPROVE,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.APPROVE,
            request_id=request_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_REJECT,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            request_id=request_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            request_id=request_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def calendar_prompt_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.CONFIRM,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.CANCEL,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(2)
    return builder.as_markup()


def admin_calendar_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CALENDAR_SEASONS,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.SEASONS),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_TOURNAMENTS,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.TOURNAMENTS),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def manual_tournaments_prompt_keyboard(prompt: TournamentPromptView) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Изменить",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=prompt.id,
        ),
    )
    builder.button(
        text="Создать",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CONFIRM,
            prompt_id=prompt.id,
        ),
    )
    builder.button(
        text="Отмена",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CANCEL,
            prompt_id=prompt.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_prompt_day_edit_keyboard(prompt: TournamentPromptView) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in prompt.tournaments:
        builder.button(
            text=texts.common.WEEKDAYS[item.date.weekday()],
            callback_data=TournamentPromptDayEditCallback(
                prompt_id=prompt.id,
                tournament_date=item.date.isoformat(),
            ),
        )
    builder.button(
        text=buttons.ADMIN_CALENDAR_BACK,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.BACK,
            prompt_id=prompt.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def season_open_confirmation_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CALENDAR_OPEN,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_EDIT,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.CHANGE,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def season_proposal_change_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_SEASON_EDIT_NAME,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.NAME,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_SEASON_EDIT_START,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.STARTS_AT,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_BACK,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.BACK,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_type_edit_keyboard(
    edit_view: TournamentPromptDayEditView,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament_type in edit_view.tournament_types:
        builder.button(
            text=tournament_type.name,
            callback_data=TournamentTypeEditCallback(
                prompt_id=edit_view.prompt_id,
                tournament_date=edit_view.tournament_date.isoformat(),
                tournament_type_id=tournament_type.id,
            ),
        )
    builder.button(
        text=buttons.ADMIN_CALENDAR_BACK,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=edit_view.prompt_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
