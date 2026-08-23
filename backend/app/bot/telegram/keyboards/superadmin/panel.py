from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.bot.telegram.keyboards import labels


def superadmin_panel_keyboard(active_telegram_users_count: int = 0) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=labels.superadmin_registrations_label(active_telegram_users_count)
                ),
                KeyboardButton(text=labels.ADMIN_PANEL_RENAME_USER),
            ],
            [
                KeyboardButton(text=labels.ADMIN_PANEL_CLOSE_TOURNAMENT),
                KeyboardButton(text=labels.ADMIN_PANEL_ADD_ADMIN),
            ],
            [
                KeyboardButton(text=labels.ADMIN_PANEL_CALENDAR),
                KeyboardButton(text=labels.ADMIN_PANEL_HALL_OF_FAME),
            ],
            [KeyboardButton(text=labels.ADMIN_PANEL_ADMIN)],
        ],
        resize_keyboard=True,
    )
