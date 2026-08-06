# ruff: noqa: F403,F405
from app.bot.telegram.keyboards.admin.common import *  # noqa: F403


class SeasonOpenAction(StrEnum):
    CONFIRM = "confirm"
    CHANGE = "change"
    NAME = "name"
    STARTS_AT = "starts_at"
    BACK = "back"
    CANCEL = "cancel"


class SeasonOpenCallback(CallbackData, prefix="season_open"):
    action: SeasonOpenAction
    prompt_id: int


def season_open_confirmation_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CALENDAR_OPEN,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_EDIT,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.CHANGE,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def season_proposal_change_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_SEASON_EDIT_NAME,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.NAME,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_SEASON_EDIT_START,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.STARTS_AT,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_BACK,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.BACK,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
