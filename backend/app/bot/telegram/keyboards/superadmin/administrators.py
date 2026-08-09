from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.services.dto.users import UserView


class AdminCandidateAction(StrEnum):
    OPEN = "open"
    SEARCH_AGAIN = "search_again"
    CANCEL = "cancel"


class AdminCandidateCallback(CallbackData, prefix="admin_candidate"):
    action: AdminCandidateAction
    player_id: int


class AdminAddAction(StrEnum):
    CONFIRM = "confirm"
    BACK = "back"
    CANCEL = "cancel"


class AdminAddCallback(CallbackData, prefix="admin_add"):
    action: AdminAddAction
    player_id: int


def admin_candidate_search_results_keyboard(candidates: list[UserView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in candidates:
        builder.button(
            text=player.display_name,
            callback_data=AdminCandidateCallback(
                action=AdminCandidateAction.OPEN,
                player_id=player.id,
            ),
        )
    builder.button(
        text="🔎 Искать снова",
        callback_data=AdminCandidateCallback(
            action=AdminCandidateAction.SEARCH_AGAIN,
            player_id=0,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCandidateCallback(
            action=AdminCandidateAction.CANCEL,
            player_id=0,
        ),
    )
    builder.adjust(*([1] * len(candidates)), 1, 1)
    return builder.as_markup()


def admin_candidate_not_found_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔎 Искать снова",
        callback_data=AdminCandidateCallback(
            action=AdminCandidateAction.SEARCH_AGAIN,
            player_id=0,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCandidateCallback(
            action=AdminCandidateAction.CANCEL,
            player_id=0,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_candidate_search_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminCandidateCallback(
            action=AdminCandidateAction.CANCEL,
            player_id=0,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_add_confirmation_keyboard(player_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_ADD_CONFIRM,
        callback_data=AdminAddCallback(
            action=AdminAddAction.CONFIRM,
            player_id=player_id,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=AdminAddCallback(
            action=AdminAddAction.BACK,
            player_id=player_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=AdminAddCallback(
            action=AdminAddAction.CANCEL,
            player_id=player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
