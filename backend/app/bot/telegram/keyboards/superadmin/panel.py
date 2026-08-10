from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.bot.telegram.keyboards import labels


def superadmin_panel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=labels.ADMIN_PANEL_REGISTRATIONS),
                KeyboardButton(text=labels.ADMIN_PANEL_ADD_ADMIN),
            ],
            [
                KeyboardButton(text=labels.ADMIN_PANEL_CALENDAR),
                KeyboardButton(text=labels.ADMIN_PANEL_CLOSE_TOURNAMENT),
            ],
            [
                KeyboardButton(text=labels.ADMIN_PANEL_HALL_OF_FAME),
                KeyboardButton(text=labels.ADMIN_PANEL_ADMIN),
            ],
        ],
        resize_keyboard=True,
    )
