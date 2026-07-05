from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(text="Расписание турниров"),
            KeyboardButton(text="Как нас найти"),
        ],
        [KeyboardButton(text="Записаться"), KeyboardButton(text="Отменить запись")],
        [KeyboardButton(text="Рейтинг"), KeyboardButton(text="Твой профиль")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="Админ-панель")])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
