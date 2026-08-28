from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.common import _admin_candidate_page_label
from app.services.dto.check_in import CheckInCandidateView, TournamentCheckInView
from app.services.dto.tournaments import TournamentView
from app.services.dto.users import UserView
from app.services.pagination import Page

ADMIN_CHECK_IN_PAGE_SIZE = 6


class AdminCheckInAction(StrEnum):
    OPEN_TOURNAMENT = "open_tournament"
    PAGE_TOURNAMENTS = "page_tournaments"
    SHOW_CHECKED_IN = "show_checked_in"
    CONFIRM_REGISTERED = "confirm_registered"
    ADD_REGISTERED = "add_registered"
    REGISTERED_SEARCH = "registered_search"
    DATABASE_SEARCH = "database_search"
    CONFIRM_EXISTING = "confirm_existing"
    ADD_EXISTING = "add_existing"
    NEW_PLAYER = "new_player"
    CONFIRM_NEW = "confirm_new"
    CREATE_NEW = "create_new"
    SKIP_REWARD = "skip_reward"
    SELECT_REWARD = "select_reward"
    CONFIRM_REWARD = "confirm_reward"
    REDEEM_REWARD = "redeem_reward"
    SET_GENDER_FEMALE = "set_gender_female"
    SET_GENDER_MALE = "set_gender_male"
    SKIP_GENDER = "skip_gender"
    CHOOSE_OTHER_NEW = "choose_other_new"
    BACK = "back"
    BACK_TO_TOURNAMENT = "back_to_tournament"
    CANCEL = "cancel"


class AdminCheckInCallback(CallbackData, prefix="check_in"):
    action: AdminCheckInAction
    tournament_id: int
    page: int = 0
    player_id: int = 0
    reward_id: int = 0


def admin_check_in_keyboard(
    view: TournamentCheckInView,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    registered_candidates = getattr(view, "registered_candidates", None) or []
    for player in registered_candidates:
        builder.button(
            text=player.display_name,
            callback_data=AdminCheckInCallback(
                action=AdminCheckInAction.CONFIRM_REGISTERED,
                tournament_id=view.tournament.id,
                player_id=player.user_id,
            ),
        )
    builder.button(
        text="✅ Зарегистрированный",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.REGISTERED_SEARCH,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text="👤 Играл ранее",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.DATABASE_SEARCH,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text="🆕 Новый игрок",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.NEW_PLAYER,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=f"👥 Уже отметились ({view.checked_in_count})",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.SHOW_CHECKED_IN,
            tournament_id=view.tournament.id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=view.tournament.id,
        ),
    )
    builder.adjust(*([1] * len(registered_candidates)), 1)
    return builder.as_markup()


def admin_check_in_tournament_list_keyboard(
    page: Page[TournamentView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament in page.items:
        builder.button(
            text=_tournament_picker_label(tournament),
            callback_data=AdminCheckInCallback(
                action=AdminCheckInAction.OPEN_TOURNAMENT,
                tournament_id=tournament.id,
                page=page.page,
            ),
        )
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=AdminCheckInCallback(
                    action=AdminCheckInAction.PAGE_TOURNAMENTS,
                    tournament_id=0,
                    page=page.previous_page,
                ),
            )
        builder.button(
            text=_admin_candidate_page_label(page),
            callback_data=AdminCheckInCallback(
                action=AdminCheckInAction.PAGE_TOURNAMENTS,
                tournament_id=0,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=AdminCheckInCallback(
                    action=AdminCheckInAction.PAGE_TOURNAMENTS,
                    tournament_id=0,
                    page=page.next_page,
                ),
            )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=0,
        ),
    )
    item_rows = [1] * len(page.items)
    footer_rows = []
    if page.total_pages > 1:
        footer_rows.append(1 + int(page.has_previous) + int(page.has_next))
    footer_rows.append(1)
    builder.adjust(*item_rows, *footer_rows)
    return builder.as_markup()


def _tournament_picker_label(tournament: TournamentView) -> str:
    return (
        f"{tournament.date.day:02d}.{tournament.date.month:02d} — "
        f"{tournament_fmt.type_name(tournament)}"
    )


def admin_checked_in_players_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.BACK_TO_TOURNAMENT,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_search_results_keyboard(
    *,
    tournament_id: int,
    players: list[CheckInCandidateView] | list[UserView],
    action: AdminCheckInAction,
    back_action: AdminCheckInAction,
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
            action=back_action,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
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
        text=labels.ADMIN_CANCEL,
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
        text=labels.ADMIN_CANCEL,
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
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_reward_selection_keyboard(
    *,
    tournament_id: int,
    player_id: int,
    rewards: tuple,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for reward in rewards:
        builder.button(
            text=f"🎁 +{fmt_common.number(reward.chips_amount)} · до {reward.valid_through:%d.%m}",
            callback_data=AdminCheckInCallback(
                action=AdminCheckInAction.CONFIRM_REWARD,
                tournament_id=tournament_id,
                player_id=player_id,
                reward_id=reward.reward_id,
            ),
        )
    builder.button(
        text="Не использовать",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.SKIP_REWARD,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_gender_keyboard(
    *,
    tournament_id: int,
    player_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👩 Женский",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.SET_GENDER_FEMALE,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.button(
        text="👨 Мужской",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.SET_GENDER_MALE,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.button(
        text="❓ Не указывать",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.SKIP_GENDER,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_check_in_reward_confirmation_keyboard(
    *,
    tournament_id: int,
    player_id: int,
    reward_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Выдать",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.REDEEM_REWARD,
            tournament_id=tournament_id,
            player_id=player_id,
            reward_id=reward_id,
        ),
    )
    builder.button(
        text="⬅️ Назад",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.SELECT_REWARD,
            tournament_id=tournament_id,
            player_id=player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
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
        text="⬅️ Назад",
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.BACK_TO_TOURNAMENT,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
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
            action=search_action,
            tournament_id=tournament_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCheckInCallback(
            action=AdminCheckInAction.CANCEL,
            tournament_id=tournament_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


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
