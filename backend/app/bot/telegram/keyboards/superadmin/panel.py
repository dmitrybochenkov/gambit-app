# ruff: noqa: F403,F405
from app.bot.telegram.keyboards.admin.common import *  # noqa: F403


def superadmin_panel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=buttons.ADMIN_PANEL_REGISTRATIONS)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_CALENDAR)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_ADD_ADMIN)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_CLOSE_TOURNAMENT)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_BACK)],
        ],
        resize_keyboard=True,
    )
