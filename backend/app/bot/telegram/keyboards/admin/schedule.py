from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.calendar import CalendarPromptAction, CalendarPromptCallback
from app.bot.telegram.texts import common as common_texts
from app.services.dto import TournamentPromptDayEditView, TournamentPromptView


class TournamentPromptDayEditCallback(CallbackData, prefix="tour_prompt_day"):
    prompt_id: int
    tournament_date: str


class TournamentTypeEditCallback(CallbackData, prefix="tournament_type_edit"):
    prompt_id: int
    tournament_date: str
    tournament_type_id: int


def manual_tournaments_prompt_keyboard(prompt: TournamentPromptView) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Изменить",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=prompt.id,
        ),
    )
    builder.button(
        text="Создать",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CONFIRM,
            prompt_id=prompt.id,
        ),
    )
    builder.button(
        text="Отмена",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CANCEL,
            prompt_id=prompt.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_prompt_day_edit_keyboard(prompt: TournamentPromptView) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in prompt.tournaments:
        builder.button(
            text=common_texts.WEEKDAYS[item.date.weekday()],
            callback_data=TournamentPromptDayEditCallback(
                prompt_id=prompt.id,
                tournament_date=item.date.isoformat(),
            ),
        )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.BACK,
            prompt_id=prompt.id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_type_edit_keyboard(
    edit_view: TournamentPromptDayEditView,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament_type in edit_view.tournament_types:
        builder.button(
            text=tournament_type.name,
            callback_data=TournamentTypeEditCallback(
                prompt_id=edit_view.prompt_id,
                tournament_date=edit_view.tournament_date.isoformat(),
                tournament_type_id=tournament_type.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=edit_view.prompt_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
