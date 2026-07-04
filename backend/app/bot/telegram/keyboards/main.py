from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Расписание турниров")],
            [KeyboardButton(text="Записаться"), KeyboardButton(text="Отменить запись")],
            [KeyboardButton(text="Рейтинг"), KeyboardButton(text="Твой профиль")],
            [KeyboardButton(text="Как нас найти")],
        ],
        resize_keyboard=True,
    )
