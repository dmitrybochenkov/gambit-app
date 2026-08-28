from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.services.dto.users import UserView


class UserRenameSearchAction(StrEnum):
    OPEN = "open"
    BACK = "back"
    CANCEL = "cancel"


class UserRenameSearchCallback(CallbackData, prefix="user_rename_search"):
    action: UserRenameSearchAction
    user_id: int


class UserEditAction(StrEnum):
    EDIT_NAME = "edit_name"
    CHANGE_GENDER = "change_gender"
    BACK = "back"
    CANCEL = "cancel"


class UserEditCallback(CallbackData, prefix="user_edit"):
    action: UserEditAction
    user_id: int


class UserGenderAction(StrEnum):
    FEMALE = "female"
    MALE = "male"
    UNKNOWN = "unknown"
    BACK = "back"
    CANCEL = "cancel"


class UserGenderCallback(CallbackData, prefix="user_gender"):
    action: UserGenderAction
    user_id: int


class UserRenameConfirmAction(StrEnum):
    CONFIRM = "confirm"
    BACK = "back"
    CANCEL = "cancel"


class UserRenameConfirmCallback(CallbackData, prefix="user_rename_confirm"):
    action: UserRenameConfirmAction
    user_id: int


def user_rename_prompt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=UserRenameSearchCallback(
            action=UserRenameSearchAction.CANCEL,
            user_id=0,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def user_rename_search_results_keyboard(candidates: list[UserView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for candidate in candidates:
        builder.button(
            text=candidate.display_name,
            callback_data=UserRenameSearchCallback(
                action=UserRenameSearchAction.OPEN,
                user_id=candidate.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_PANEL_BACK,
        callback_data=UserRenameSearchCallback(
            action=UserRenameSearchAction.BACK,
            user_id=0,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=UserRenameSearchCallback(
            action=UserRenameSearchAction.CANCEL,
            user_id=0,
        ),
    )
    builder.adjust(*([1] * len(candidates)), 1, 1)
    return builder.as_markup()


def user_edit_card_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Изменить имя",
        callback_data=UserEditCallback(action=UserEditAction.EDIT_NAME, user_id=user_id),
    )
    builder.button(
        text="⚧ Изменить пол",
        callback_data=UserEditCallback(action=UserEditAction.CHANGE_GENDER, user_id=user_id),
    )
    builder.button(
        text=labels.ADMIN_PANEL_BACK,
        callback_data=UserEditCallback(action=UserEditAction.BACK, user_id=user_id),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=UserEditCallback(action=UserEditAction.CANCEL, user_id=user_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def user_gender_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="👩 Женский",
        callback_data=UserGenderCallback(action=UserGenderAction.FEMALE, user_id=user_id),
    )
    builder.button(
        text="👨 Мужской",
        callback_data=UserGenderCallback(action=UserGenderAction.MALE, user_id=user_id),
    )
    builder.button(
        text="❓ Не указан",
        callback_data=UserGenderCallback(action=UserGenderAction.UNKNOWN, user_id=user_id),
    )
    builder.button(
        text=labels.ADMIN_PANEL_BACK,
        callback_data=UserGenderCallback(action=UserGenderAction.BACK, user_id=user_id),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=UserGenderCallback(action=UserGenderAction.CANCEL, user_id=user_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def user_rename_confirmation_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Переименовать",
        callback_data=UserRenameConfirmCallback(
            action=UserRenameConfirmAction.CONFIRM,
            user_id=user_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_PANEL_BACK,
        callback_data=UserRenameConfirmCallback(
            action=UserRenameConfirmAction.BACK,
            user_id=user_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=UserRenameConfirmCallback(
            action=UserRenameConfirmAction.CANCEL,
            user_id=user_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
