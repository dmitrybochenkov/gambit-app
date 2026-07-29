from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.bot.telegram.keyboards import buttons
from app.services.dto import UserView


def main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(text=buttons.MAIN_SCHEDULE),
            KeyboardButton(text=buttons.MAIN_ADDRESS),
        ],
        [
            KeyboardButton(text=buttons.MAIN_REGISTER),
            KeyboardButton(text=buttons.MAIN_CANCEL_REGISTRATION),
        ],
        [KeyboardButton(text=buttons.MAIN_RATING), KeyboardButton(text=buttons.MAIN_PROFILE)],
        [
            KeyboardButton(text=buttons.MAIN_HISTORY),
            KeyboardButton(text=buttons.MAIN_HALL_OF_FAME),
        ],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=buttons.MAIN_ADMIN)])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def main_keyboard_for_player(player: UserView) -> ReplyKeyboardMarkup:
    return main_keyboard(is_admin=player.is_admin)


def main_keyboard_after_registration() -> ReplyKeyboardMarkup:
    return main_keyboard(is_admin=False)


def main_keyboard_after_role_update(player: UserView) -> ReplyKeyboardMarkup:
    return main_keyboard_for_player(player)
