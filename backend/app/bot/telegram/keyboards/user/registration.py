from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

REGISTRATION_NEW_PLAYER_CALLBACK = "registration:new_player"
REGISTRATION_LINK_EXISTING_CALLBACK = "registration:link_existing"
REGISTRATION_RETRY_LINK_CALLBACK = "registration:retry_link"
REGISTRATION_BACK_CALLBACK = "registration:back"
REGISTRATION_CONFIRM_NEW_CALLBACK = "registration:new_confirm"
REGISTRATION_CHANGE_NEW_CALLBACK = "registration:new_change"
REGISTRATION_CANCEL_NEW_CALLBACK = "registration:new_cancel"


def registration_start_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🆕 Нет, я новый игрок", callback_data=REGISTRATION_NEW_PLAYER_CALLBACK)
    builder.button(text="🔗 Да, играл ранее", callback_data=REGISTRATION_LINK_EXISTING_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()


def registration_link_not_found_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Повторить поиск", callback_data=REGISTRATION_RETRY_LINK_CALLBACK)
    builder.button(text="⬅️ Вернуться назад", callback_data=REGISTRATION_BACK_CALLBACK)
    builder.button(
        text="🆕 Зарегистрироваться как новый игрок",
        callback_data=REGISTRATION_NEW_PLAYER_CALLBACK,
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_new_player_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=REGISTRATION_CONFIRM_NEW_CALLBACK)
    builder.button(text="✏️ Изменить", callback_data=REGISTRATION_CHANGE_NEW_CALLBACK)
    builder.button(text="❌ Отмена", callback_data=REGISTRATION_CANCEL_NEW_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()
