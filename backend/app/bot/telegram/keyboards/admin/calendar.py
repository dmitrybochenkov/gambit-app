from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels


class CalendarPlanAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    EDIT = "edit"
    BACK = "back"
    PUBLISH_PREVIEW = "publish_preview"
    PUBLISH_CONFIRM = "publish_confirm"


class CalendarPlanCallback(CallbackData, prefix="calendar_plan"):
    action: CalendarPlanAction


class AdminCalendarAction(StrEnum):
    SEASONS = "seasons"
    TOURNAMENTS = "tournaments"
    CANCEL = "cancel"


class AdminCalendarCallback(CallbackData, prefix="admin_calendar"):
    action: AdminCalendarAction


def calendar_plan_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.CONFIRM,
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.CONFIRM),
    )
    builder.button(
        text=labels.CANCEL,
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.CANCEL),
    )
    builder.adjust(2)
    return builder.as_markup()


def admin_calendar_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_CALENDAR_SEASONS,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.SEASONS),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_TOURNAMENTS,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.TOURNAMENTS),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def schedule_publication_action_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📣 Опубликовать расписание",
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.PUBLISH_PREVIEW),
    )
    builder.adjust(1)
    return builder.as_markup()


def schedule_publication_preview_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Опубликовать",
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.PUBLISH_CONFIRM),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.PUBLISH_PREVIEW),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=CalendarPlanCallback(action=CalendarPlanAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()
