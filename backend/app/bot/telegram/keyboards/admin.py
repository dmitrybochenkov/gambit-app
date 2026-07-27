import json
from datetime import date
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram import texts
from app.bot.telegram.keyboards import buttons
from app.services.dto import (
    AdminPromptView,
    RegistrationCandidateView,
    RegistrationReviewView,
    TournamentResultDraftPlayerView,
    TournamentResultDraftView,
    TournamentTypeOptionView,
    TournamentView,
    UserView,
)
from app.services.pagination import Page

REGISTRATION_LIST_PAGE_SIZE = 6
ADMIN_CANDIDATE_PAGE_SIZE = 6
ADMIN_RESULT_PAGE_SIZE = 6
ADMIN_TOURNAMENT_REGISTRATION_PAGE_SIZE = 6
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


class CalendarPromptCallback(CallbackData, prefix="calendar_prompt"):
    action: CalendarPromptAction
    prompt_id: int


class AdminCalendarAction(StrEnum):
    SEASONS = "seasons"
    TOURNAMENTS = "tournaments"
    CANCEL = "cancel"


class AdminCalendarCallback(CallbackData, prefix="admin_calendar"):
    action: AdminCalendarAction


class SeasonEditAction(StrEnum):
    NAME = "name"
    STARTS_AT = "starts_at"
    ENDS_AT = "ends_at"
    CANCEL = "cancel"


class SeasonEditCallback(CallbackData, prefix="season_edit"):
    action: SeasonEditAction
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
    POOL = "pool"
    PLAYERS = "players"
    CLOSE = "close"
    CANCEL = "cancel"


class AdminResultMenuCallback(CallbackData, prefix="res_menu"):
    action: AdminResultMenuAction
    tournament_id: int


class AdminResultCloseAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"


class AdminResultCloseCallback(CallbackData, prefix="res_close"):
    action: AdminResultCloseAction
    tournament_id: int


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
    PLACE = "place"


class AdminResultFieldAction(StrEnum):
    OPEN = "open"
    DONE = "done"
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


class AdminTournamentRegistrationTournamentAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class AdminTournamentRegistrationTournamentCallback(CallbackData, prefix="admin_reg_t"):
    action: AdminTournamentRegistrationTournamentAction
    page: int
    tournament_id: int


class AdminTournamentRegistrationPlayerAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    SEARCH = "search"
    BACK = "back"
    CANCEL = "cancel"


class AdminTournamentRegistrationPlayerCallback(CallbackData, prefix="admin_reg_p"):
    action: AdminTournamentRegistrationPlayerAction
    tournament_id: int
    page: int
    player_id: int


class TournamentEditAction(StrEnum):
    TYPE = "type"
    ECONOMY = "economy"
    REBUYS = "rebuys"
    CANCEL = "cancel"


class TournamentEditCallback(CallbackData, prefix="tournament_edit"):
    action: TournamentEditAction
    prompt_id: int
    tournament_index: int


class TournamentDayEditAction(StrEnum):
    OPEN = "open"
    CANCEL = "cancel"


class TournamentDayEditCallback(CallbackData, prefix="tournament_day_edit"):
    action: TournamentDayEditAction
    prompt_id: int
    tournament_index: int


class TournamentTypeEditCallback(CallbackData, prefix="tournament_type_edit"):
    prompt_id: int
    tournament_index: int
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
        [KeyboardButton(text=buttons.ADMIN_PANEL_REGISTER_PLAYER)],
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


def admin_result_menu_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_RESULTS_POOL,
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.POOL,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_RESULTS_PLAYERS,
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.PLAYERS,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_RESULTS_CLOSE,
        callback_data=AdminResultMenuCallback(
            action=AdminResultMenuAction.CLOSE,
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


def admin_result_close_confirmation_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Подтвердить",
        callback_data=AdminResultCloseCallback(
            action=AdminResultCloseAction.CONFIRM,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminResultCloseCallback(
            action=AdminResultCloseAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_result_players_keyboard(
    draft: TournamentResultDraftView,
    page: Page[TournamentResultDraftPlayerView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in page.items:
        builder.button(
            text=_admin_result_player_button_text(draft, player),
            callback_data=AdminResultPlayerCallback(
                action=AdminResultPlayerAction.OPEN,
                tournament_id=draft.tournament.id,
                page=page.page,
                player_id=player.player_id,
            ),
        )
    _add_result_player_page_buttons(builder, page, draft.tournament.id)
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.BACK,
            tournament_id=draft.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminResultPlayerCallback(
            action=AdminResultPlayerAction.CANCEL,
            tournament_id=draft.tournament.id,
            page=page.page,
            player_id=0,
        ),
    )
    item_rows = [1] * len(page.items)
    _adjust_paged_keyboard(builder, page, item_rows=item_rows, footer_rows=[1, 1])
    return builder.as_markup()


def _admin_result_player_button_text(
    draft: TournamentResultDraftView,
    player: TournamentResultDraftPlayerView,
) -> str:
    result_parts = []
    if player.place is not None:
        result_parts.append(PLACE_EMOJIS.get(player.place, str(player.place)))
    if draft.knockout_mode == "small_big" and player.big_knockouts_count > 0:
        result_parts.append(f"💥🥊 х{player.big_knockouts_count}")
    if draft.knockout_mode in {"small", "small_big"} and player.knockouts_count > 0:
        result_parts.append(f"🥊 х{player.knockouts_count}")
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
    draft: TournamentResultDraftView,
    player: TournamentResultDraftPlayerView,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if draft.knockout_mode in {"small", "small_big"}:
        builder.button(
            text="🥊 КО",
            callback_data=AdminResultFieldCallback(
                action=AdminResultFieldAction.OPEN,
                tournament_id=draft.tournament.id,
                page=page,
                player_id=player.player_id,
                field=AdminResultField.KNOCKOUTS,
            ),
        )
    if draft.knockout_mode == "small_big":
        builder.button(
            text="💥🥊 Большие КО",
            callback_data=AdminResultFieldCallback(
                action=AdminResultFieldAction.OPEN,
                tournament_id=draft.tournament.id,
                page=page,
                player_id=player.player_id,
                field=AdminResultField.BIG_KNOCKOUTS,
            ),
        )
    builder.button(
        text="🏁 Место",
        callback_data=AdminResultFieldCallback(
            action=AdminResultFieldAction.OPEN,
            tournament_id=draft.tournament.id,
            page=page,
            player_id=player.player_id,
            field=AdminResultField.PLACE,
        ),
    )
    builder.button(
        text="✅ Готово",
        callback_data=AdminResultFieldCallback(
            action=AdminResultFieldAction.DONE,
            tournament_id=draft.tournament.id,
            page=page,
            player_id=player.player_id,
            field=AdminResultField.PLACE,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminResultFieldCallback(
            action=AdminResultFieldAction.CANCEL,
            tournament_id=draft.tournament.id,
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
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    max_value = 5 if field == AdminResultField.PLACE else 15
    occupied_places = occupied_places or set()
    for value in range(1, max_value + 1):
        text = (
            f"✔️ {value}"
            if field == AdminResultField.PLACE and value in occupied_places
            else str(value)
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


def admin_tournament_registration_tournament_keyboard(
    page: Page[TournamentView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament in page.items:
        builder.button(
            text=str(tournament.id),
            callback_data=AdminTournamentRegistrationTournamentCallback(
                action=AdminTournamentRegistrationTournamentAction.OPEN,
                page=page.page,
                tournament_id=tournament.id,
            ),
        )
    _add_admin_registration_tournament_page_buttons(builder, page)
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminTournamentRegistrationTournamentCallback(
            action=AdminTournamentRegistrationTournamentAction.CANCEL,
            page=page.page,
            tournament_id=0,
        ),
    )
    item_rows = [3] * (len(page.items) // 3)
    if len(page.items) % 3:
        item_rows.append(len(page.items) % 3)
    _adjust_paged_keyboard(builder, page, item_rows=item_rows)
    return builder.as_markup()


def admin_tournament_registration_player_keyboard(
    tournament_id: int,
    page: Page[UserView],
    search_again: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=(
            buttons.ADMIN_TOURNAMENT_REGISTRATION_SEARCH_AGAIN
            if search_again
            else buttons.ADMIN_TOURNAMENT_REGISTRATION_SEARCH
        ),
        callback_data=AdminTournamentRegistrationPlayerCallback(
            action=AdminTournamentRegistrationPlayerAction.SEARCH,
            tournament_id=tournament_id,
            page=page.page,
            player_id=0,
        ),
    )
    for player in page.items:
        builder.button(
            text=f"{player.id}. {player.display_name}",
            callback_data=AdminTournamentRegistrationPlayerCallback(
                action=AdminTournamentRegistrationPlayerAction.OPEN,
                tournament_id=tournament_id,
                page=page.page,
                player_id=player.id,
            ),
        )
    _add_admin_registration_player_page_buttons(builder, page, tournament_id)
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminTournamentRegistrationPlayerCallback(
            action=AdminTournamentRegistrationPlayerAction.BACK,
            tournament_id=tournament_id,
            page=page.page,
            player_id=0,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminTournamentRegistrationPlayerCallback(
            action=AdminTournamentRegistrationPlayerAction.CANCEL,
            tournament_id=tournament_id,
            page=page.page,
            player_id=0,
        ),
    )
    _adjust_paged_keyboard(
        builder,
        page,
        item_rows=[1] + [1] * len(page.items),
        footer_rows=[1, 1],
    )
    return builder.as_markup()


def admin_tournament_registration_search_cancel_keyboard(
    tournament_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminTournamentRegistrationPlayerCallback(
            action=AdminTournamentRegistrationPlayerAction.CANCEL,
            tournament_id=tournament_id,
            page=0,
            player_id=0,
        ),
    )
    return builder.as_markup()


def _admin_candidate_page_label(page: Page[UserView]) -> str:
    start = page.page * page.page_size + 1
    end = start + len(page.items) - 1
    return f"{start}-{end} из {page.total_items}"


def _add_admin_registration_tournament_page_buttons(
    builder: InlineKeyboardBuilder,
    page: Page[TournamentView],
) -> None:
    if page.total_pages <= 1:
        return
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=AdminTournamentRegistrationTournamentCallback(
                action=AdminTournamentRegistrationTournamentAction.PAGE,
                page=page.previous_page,
                tournament_id=0,
            ),
        )
    builder.button(
        text=_admin_candidate_page_label(page),
        callback_data=AdminTournamentRegistrationTournamentCallback(
            action=AdminTournamentRegistrationTournamentAction.PAGE,
            page=page.page,
            tournament_id=0,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=AdminTournamentRegistrationTournamentCallback(
                action=AdminTournamentRegistrationTournamentAction.PAGE,
                page=page.next_page,
                tournament_id=0,
            ),
        )


def _add_admin_registration_player_page_buttons(
    builder: InlineKeyboardBuilder,
    page: Page[UserView],
    tournament_id: int,
) -> None:
    if page.total_pages <= 1:
        return
    if page.has_previous:
        builder.button(
            text="⬅️",
            callback_data=AdminTournamentRegistrationPlayerCallback(
                action=AdminTournamentRegistrationPlayerAction.PAGE,
                tournament_id=tournament_id,
                page=page.previous_page,
                player_id=0,
            ),
        )
    builder.button(
        text=_admin_candidate_page_label(page),
        callback_data=AdminTournamentRegistrationPlayerCallback(
            action=AdminTournamentRegistrationPlayerAction.PAGE,
            tournament_id=tournament_id,
            page=page.page,
            player_id=0,
        ),
    )
    if page.has_next:
        builder.button(
            text="➡️",
            callback_data=AdminTournamentRegistrationPlayerCallback(
                action=AdminTournamentRegistrationPlayerAction.PAGE,
                tournament_id=tournament_id,
                page=page.next_page,
                player_id=0,
            ),
        )


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
    page: Page[TournamentResultDraftPlayerView],
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


def manual_season_prompt_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CALENDAR_OPEN,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_EDIT,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(2, 1)
    return builder.as_markup()


def manual_tournaments_prompt_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CALENDAR_OPEN,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_EDIT,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(2, 1)
    return builder.as_markup()


def season_edit_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_SEASON_EDIT_NAME,
        callback_data=SeasonEditCallback(
            action=SeasonEditAction.NAME,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_SEASON_EDIT_START,
        callback_data=SeasonEditCallback(
            action=SeasonEditAction.STARTS_AT,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_SEASON_EDIT_END,
        callback_data=SeasonEditCallback(
            action=SeasonEditAction.ENDS_AT,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=SeasonEditCallback(
            action=SeasonEditAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_day_edit_keyboard(prompt: AdminPromptView) -> InlineKeyboardMarkup:
    payload = json.loads(prompt.payload)
    builder = InlineKeyboardBuilder()
    for index, item in enumerate(payload["tournaments"]):
        tournament_date = date.fromisoformat(item["date"])
        builder.button(
            text=(
                f"{texts.common.WEEKDAYS[tournament_date.weekday()]}, "
                f"{tournament_date.day}.{tournament_date.month:02d}."
                f"{tournament_date.year}"
            ),
            callback_data=TournamentDayEditCallback(
                action=TournamentDayEditAction.OPEN,
                prompt_id=prompt.id,
                tournament_index=index,
            ),
        )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=TournamentDayEditCallback(
            action=TournamentDayEditAction.CANCEL,
            prompt_id=prompt.id,
            tournament_index=0,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_field_edit_keyboard(
    prompt_id: int,
    tournament_index: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_TOURNAMENT_EDIT_TYPE,
        callback_data=TournamentEditCallback(
            action=TournamentEditAction.TYPE,
            prompt_id=prompt_id,
            tournament_index=tournament_index,
        ),
    )
    builder.button(
        text=buttons.ADMIN_TOURNAMENT_EDIT_ECONOMY,
        callback_data=TournamentEditCallback(
            action=TournamentEditAction.ECONOMY,
            prompt_id=prompt_id,
            tournament_index=tournament_index,
        ),
    )
    builder.button(
        text=buttons.ADMIN_TOURNAMENT_EDIT_REBUYS,
        callback_data=TournamentEditCallback(
            action=TournamentEditAction.REBUYS,
            prompt_id=prompt_id,
            tournament_index=tournament_index,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=TournamentEditCallback(
            action=TournamentEditAction.CANCEL,
            prompt_id=prompt_id,
            tournament_index=tournament_index,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_type_edit_keyboard(
    prompt_id: int,
    tournament_index: int,
    tournament_types: list[TournamentTypeOptionView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament_type in tournament_types:
        builder.button(
            text=tournament_type.name,
            callback_data=TournamentTypeEditCallback(
                prompt_id=prompt_id,
                tournament_index=tournament_index,
                tournament_type_id=tournament_type.id,
            ),
        )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=TournamentEditCallback(
            action=TournamentEditAction.CANCEL,
            prompt_id=prompt_id,
            tournament_index=tournament_index,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_edit_cancel_keyboard(
    prompt_id: int,
    tournament_index: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=TournamentEditCallback(
            action=TournamentEditAction.CANCEL,
            prompt_id=prompt_id,
            tournament_index=tournament_index,
        ),
    )
    return builder.as_markup()
