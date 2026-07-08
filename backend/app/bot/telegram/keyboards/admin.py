from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class RegistrationReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class RegistrationReviewCallback(CallbackData, prefix="registration_review"):
    action: RegistrationReviewAction
    player_id: int


class CalendarPromptAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    EDIT = "edit"


class CalendarPromptCallback(CallbackData, prefix="calendar_prompt"):
    action: CalendarPromptAction
    prompt_id: int


def registration_review_keyboard(player_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Одобрить",
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.APPROVE,
            player_id=player_id,
        ),
    )
    builder.button(
        text="Отклонить",
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            player_id=player_id,
        ),
    )
    builder.adjust(2)
    return builder.as_markup()


def calendar_prompt_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Подтвердить",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text="Отмена",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text="Исправить",
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(2, 1)
    return builder.as_markup()
