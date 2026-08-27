from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.bot.telegram.keyboards import labels


def superadmin_panel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=labels.ADMIN_PANEL_REGISTRATIONS),
                KeyboardButton(text=labels.ADMIN_PANEL_RENAME_USER),
            ],
            [
                KeyboardButton(text=labels.SUPERADMIN_PANEL_TOURNAMENTS),
                KeyboardButton(text=labels.ADMIN_PANEL_ADD_ADMIN),
            ],
            [
                KeyboardButton(text=labels.SUPERADMIN_PANEL_SEASONS),
                KeyboardButton(text=labels.ADMIN_PANEL_HALL_OF_FAME),
            ],
            [KeyboardButton(text=labels.ADMIN_PANEL_ADMIN)],
        ],
        resize_keyboard=True,
    )
