from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.bot.telegram.keyboards import labels
from app.services.dto import UserRoleView, UserView


def admin_panel_keyboard(admin: UserView) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=labels.ADMIN_PANEL_CHECK_IN)],
        [KeyboardButton(text=labels.ADMIN_PANEL_RESULTS)],
    ]
    if admin.role == UserRoleView.SUPERADMIN:
        keyboard.append([KeyboardButton(text=labels.ADMIN_PANEL_SUPERADMIN)])
    keyboard.append([KeyboardButton(text=labels.ADMIN_PANEL_EXIT)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )
