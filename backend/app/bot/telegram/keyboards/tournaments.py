from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters import format_tournament_label
from app.db.models import Tournament


class TournamentRegistrationCallback(CallbackData, prefix="tournament_register"):
    tournament_id: int


def tournament_registration_keyboard(
    tournaments: list[Tournament],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        builder.button(
            text=format_tournament_label(tournament),
            callback_data=TournamentRegistrationCallback(tournament_id=tournament.id),
        )
    builder.adjust(1)
    return builder.as_markup()
