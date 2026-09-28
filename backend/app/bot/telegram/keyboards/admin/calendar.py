from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels


class CalendarPlanAction(StrEnum):
    CANCEL = "cancel"
    PUBLISH_PREVIEW = "publish_preview"
    PUBLISH_CONFIRM = "publish_confirm"


class CalendarPlanCallback(CallbackData, prefix="calendar_plan"):
    action: CalendarPlanAction


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
