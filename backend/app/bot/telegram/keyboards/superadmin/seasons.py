from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels


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


class SeasonManageAction(StrEnum):
    CREATE_NEXT = "create_next"
    LIST = "list"
    LIST_PAGE = "list_page"
    DELETE_FUTURE = "delete_future"
    CANCEL = "cancel"


class SeasonManageCallback(CallbackData, prefix="season_manage"):
    action: SeasonManageAction
    page: int = 0
    season_id: int = 0


class SeasonDeleteFutureAction(StrEnum):
    CONFIRM = "confirm"
    BACK = "back"
    CANCEL = "cancel"


class SeasonDeleteFutureCallback(CallbackData, prefix="season_future_delete"):
    action: SeasonDeleteFutureAction
    season_id: int


def season_management_keyboard(
    *,
    can_create: bool,
    can_delete_future: bool,
    future_season_id: int | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_create:
        builder.button(
            text="➕ Создать следующий сезон",
            callback_data=SeasonManageCallback(action=SeasonManageAction.CREATE_NEXT),
        )
    if can_delete_future and future_season_id is not None:
        builder.button(
            text="🗑 Удалить будущий сезон",
            callback_data=SeasonManageCallback(
                action=SeasonManageAction.DELETE_FUTURE,
                season_id=future_season_id,
            ),
        )
    builder.button(
        text="📋 Все сезоны",
        callback_data=SeasonManageCallback(action=SeasonManageAction.LIST),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=SeasonManageCallback(action=SeasonManageAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def season_list_keyboard(page: object) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=SeasonManageCallback(
                    action=SeasonManageAction.LIST_PAGE,
                    page=page.previous_page,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=SeasonManageCallback(
                action=SeasonManageAction.LIST_PAGE,
                page=page.page,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=SeasonManageCallback(
                    action=SeasonManageAction.LIST_PAGE,
                    page=page.next_page,
                ),
            )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SeasonManageCallback(action=SeasonManageAction.LIST_PAGE, page=-1),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=SeasonManageCallback(action=SeasonManageAction.CANCEL),
    )
    if page.total_pages > 1:
        navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
        builder.adjust(navigation_buttons, 1, 1)
    else:
        builder.adjust(1, 1)
    return builder.as_markup()


def season_input_navigation_keyboard(prompt_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if prompt_id is None:
        builder.button(
            text=labels.ADMIN_CALENDAR_BACK,
            callback_data=SeasonManageCallback(action=SeasonManageAction.LIST_PAGE, page=-1),
        )
        builder.button(
            text=labels.ADMIN_CALENDAR_CANCEL,
            callback_data=SeasonManageCallback(action=SeasonManageAction.CANCEL),
        )
    else:
        builder.button(
            text=labels.ADMIN_CALENDAR_BACK,
            callback_data=SeasonOpenCallback(action=SeasonOpenAction.BACK, prompt_id=prompt_id),
        )
        builder.button(
            text=labels.ADMIN_CALENDAR_CANCEL,
            callback_data=SeasonOpenCallback(action=SeasonOpenAction.CANCEL, prompt_id=prompt_id),
        )
    builder.adjust(1)
    return builder.as_markup()


def season_delete_future_confirmation_keyboard(season_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Удалить",
        callback_data=SeasonDeleteFutureCallback(
            action=SeasonDeleteFutureAction.CONFIRM,
            season_id=season_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SeasonDeleteFutureCallback(
            action=SeasonDeleteFutureAction.BACK,
            season_id=season_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
        callback_data=SeasonDeleteFutureCallback(
            action=SeasonDeleteFutureAction.CANCEL,
            season_id=season_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def season_open_confirmation_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=labels.ADMIN_CALENDAR_OPEN,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_EDIT,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.CHANGE,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_CANCEL,
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
        text=labels.ADMIN_SEASON_EDIT_NAME,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.NAME,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_SEASON_EDIT_START,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.STARTS_AT,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CALENDAR_BACK,
        callback_data=SeasonOpenCallback(
            action=SeasonOpenAction.BACK,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
