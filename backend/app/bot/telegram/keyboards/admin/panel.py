from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.bot.telegram.keyboards import labels
from app.db.models.enums import UserRole
from app.services.dto.users import UserView


def admin_panel_keyboard(admin: UserView) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=labels.ADMIN_PANEL_CHECK_IN)],
        [KeyboardButton(text=labels.ADMIN_PANEL_RESULTS)],
    ]
    if admin.role == UserRole.SUPERADMIN:
        keyboard.append([KeyboardButton(text=labels.ADMIN_PANEL_SUPERADMIN)])
    keyboard.append([KeyboardButton(text=labels.ADMIN_PANEL_EXIT)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )
