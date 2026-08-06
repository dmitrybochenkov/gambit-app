# ruff: noqa: F403,F405
from app.bot.telegram.keyboards.admin.common import *  # noqa: F403


def admin_panel_keyboard(admin: UserView) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=buttons.ADMIN_PANEL_CHECK_IN)],
        [KeyboardButton(text=buttons.ADMIN_PANEL_RESULTS)],
        [KeyboardButton(text=buttons.ADMIN_PANEL_SUPERADMIN)],
    ]
    keyboard.append([KeyboardButton(text=buttons.ADMIN_PANEL_EXIT)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )
