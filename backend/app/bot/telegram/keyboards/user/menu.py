from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.bot.telegram.keyboards import labels
from app.services.dto.users import UserView


def main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(text=labels.MAIN_SCHEDULE),
            KeyboardButton(text=labels.MAIN_ADDRESS),
        ],
        [
            KeyboardButton(text=labels.MAIN_REGISTER),
            KeyboardButton(text=labels.MAIN_CANCEL_REGISTRATION),
        ],
        [KeyboardButton(text=labels.MAIN_RATING), KeyboardButton(text=labels.MAIN_PROFILE)],
        [
            KeyboardButton(text=labels.MAIN_HISTORY),
            KeyboardButton(text=labels.MAIN_HALL_OF_FAME),
        ],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=labels.MAIN_ADMIN)])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def main_keyboard_for_player(player: UserView) -> ReplyKeyboardMarkup:
    return main_keyboard(is_admin=player.is_admin)


def main_keyboard_after_registration() -> ReplyKeyboardMarkup:
    return main_keyboard(is_admin=False)


def main_keyboard_after_role_update(player: UserView) -> ReplyKeyboardMarkup:
    return main_keyboard_for_player(player)
