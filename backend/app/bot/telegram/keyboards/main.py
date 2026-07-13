from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.bot.telegram.keyboards import buttons


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
    ]
    if is_admin:
        rows.append([KeyboardButton(text=buttons.MAIN_ADMIN)])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
