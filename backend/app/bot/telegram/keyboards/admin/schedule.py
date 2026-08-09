from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin.calendar import CalendarPlanAction, CalendarPlanCallback
from app.bot.telegram.texts import common as common_texts
from app.services.dto.schedules import TournamentPromptDayEditView, WeeklyTournamentPlanView


class TournamentPromptDayEditCallback(CallbackData, prefix="tour_prompt_day"):
    tournament_date: str


class TournamentTypeEditCallback(CallbackData, prefix="tournament_type_edit"):
    tournament_date: str
    tournament_type_id: int


def manual_tournaments_prompt_keyboard(plan: WeeklyTournamentPlanView) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Изменить",
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.EDIT),
    )
    builder.button(
        text="Создать",
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.CONFIRM),
    )
    builder.button(
        text="Отмена",
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_prompt_day_edit_keyboard(plan: WeeklyTournamentPlanView) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in plan.tournaments:
        builder.button(
            text=common_texts.WEEKDAYS[item.date.weekday()],
            callback_data=TournamentPromptDayEditCallback(
                tournament_date=item.date.isoformat(),
            ),
        )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.BACK),
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
                tournament_date=edit_view.tournament_date.isoformat(),
                tournament_type_id=tournament_type.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.EDIT),
    )
    builder.adjust(1)
    return builder.as_markup()
