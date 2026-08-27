from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels


class SuperadminTournamentHubAction(StrEnum):
    CREATE = "create"
    OPEN = "open"
    CLOSED = "closed"
    BACK = "back"


class SuperadminTournamentHubCallback(CallbackData, prefix="superadmin_tournaments"):
    action: SuperadminTournamentHubAction


def tournament_hub_keyboard(open_tournaments_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Создать",
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.CREATE),
    )
    builder.button(
        text=f"🔓 Открытые ({open_tournaments_count})",
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.OPEN),
    )
    builder.button(
        text="🔒 Закрытые",
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.CLOSED),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SuperadminTournamentHubCallback(action=SuperadminTournamentHubAction.BACK),
    )
    builder.adjust(1)
    return builder.as_markup()
