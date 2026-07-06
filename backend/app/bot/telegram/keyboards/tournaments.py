from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.formatters import format_tournament_label
from app.db.models import Tournament


class TournamentRegistrationCallback(CallbackData, prefix="tournament_register"):
    tournament_id: int


class TournamentCancellationCallback(CallbackData, prefix="tournament_cancel"):
    tournament_id: int


CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK = "tournament_registration:confirm"
CANCEL_TOURNAMENT_REGISTRATION_CALLBACK = "tournament_registration:cancel"
CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK = "tournament_cancellation:confirm"
CANCEL_TOURNAMENT_CANCELLATION_CALLBACK = "tournament_cancellation:cancel"


def tournament_registration_keyboard(
    tournaments: list[Tournament],
    selected_tournament_ids: set[int] | None = None,
) -> InlineKeyboardMarkup:
    selected_tournament_ids = selected_tournament_ids or set()
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        prefix = "✅ " if tournament.id in selected_tournament_ids else ""
        builder.button(
            text=f"{prefix}{format_tournament_label(tournament)}",
            callback_data=TournamentRegistrationCallback(tournament_id=tournament.id),
        )
    builder.button(
        text="Подтвердить",
        callback_data=CONFIRM_TOURNAMENT_REGISTRATION_CALLBACK,
    )
    builder.button(
        text="Отмена",
        callback_data=CANCEL_TOURNAMENT_REGISTRATION_CALLBACK,
    )
    builder.adjust(*([1] * len(tournaments)), 2)
    return builder.as_markup()


def tournament_cancellation_keyboard(
    tournaments: list[Tournament],
    selected_tournament_ids: set[int] | None = None,
) -> InlineKeyboardMarkup:
    selected_tournament_ids = selected_tournament_ids or set()
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        prefix = "✅ " if tournament.id in selected_tournament_ids else ""
        builder.button(
            text=f"{prefix}{format_tournament_label(tournament)}",
            callback_data=TournamentCancellationCallback(tournament_id=tournament.id),
        )
    builder.button(
        text="Подтвердить",
        callback_data=CONFIRM_TOURNAMENT_CANCELLATION_CALLBACK,
    )
    builder.button(
        text="Отмена",
        callback_data=CANCEL_TOURNAMENT_CANCELLATION_CALLBACK,
    )
    builder.adjust(*([1] * len(tournaments)), 2)
    return builder.as_markup()
