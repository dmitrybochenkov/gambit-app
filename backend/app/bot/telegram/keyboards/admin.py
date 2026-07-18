from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import buttons
from app.services.dto import RegistrationMatchView, RegistrationReviewView
from app.services.pagination import Page

REGISTRATION_LIST_PAGE_SIZE = 6


class RegistrationReviewAction(StrEnum):
    APPROVE = "approve"
    APPROVE_NEW = "approve_new"
    REJECT = "reject"
    CANCEL = "cancel"


class RegistrationReviewCallback(CallbackData, prefix="registration_review"):
    action: RegistrationReviewAction
    player_id: int


class RegistrationMatchSelectionCallback(CallbackData, prefix="registration_match"):
    player_id: int
    historical_player_id: int


class RegistrationListAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class RegistrationListCallback(CallbackData, prefix="registration_list"):
    action: RegistrationListAction
    page: int
    player_id: int


class CalendarPromptAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    EDIT = "edit"


class CalendarPromptCallback(CallbackData, prefix="calendar_prompt"):
    action: CalendarPromptAction
    prompt_id: int


class AdminCalendarAction(StrEnum):
    SEASONS = "seasons"
    TOURNAMENTS = "tournaments"
    CANCEL = "cancel"


class AdminCalendarCallback(CallbackData, prefix="admin_calendar"):
    action: AdminCalendarAction


def registration_review_keyboard(
    player_id: int,
    has_matches: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_APPROVE_WITH_HISTORY if has_matches else buttons.ADMIN_APPROVE,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.APPROVE,
            player_id=player_id,
        ),
    )
    if has_matches:
        builder.button(
            text=buttons.ADMIN_APPROVE_AS_NEW,
            callback_data=RegistrationReviewCallback(
                action=RegistrationReviewAction.APPROVE_NEW,
                player_id=player_id,
            ),
        )
    builder.button(
        text=buttons.ADMIN_REJECT,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            player_id=player_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            player_id=player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_panel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=buttons.ADMIN_PANEL_REGISTRATIONS)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_CALENDAR)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_ADD_ADMIN)],
            [KeyboardButton(text=buttons.ADMIN_PANEL_EXIT)],
        ],
        resize_keyboard=True,
    )


def registration_list_keyboard(page: Page[RegistrationReviewView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for review in page.items:
        builder.button(
            text=str(review.player.id),
            callback_data=RegistrationListCallback(
                action=RegistrationListAction.OPEN,
                page=page.page,
                player_id=review.player.id,
            ),
        )

    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=RegistrationListCallback(
                    action=RegistrationListAction.PAGE,
                    page=page.previous_page,
                    player_id=0,
                ),
            )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=RegistrationListCallback(
                    action=RegistrationListAction.PAGE,
                    page=page.next_page,
                    player_id=0,
                ),
            )

    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=RegistrationListCallback(
            action=RegistrationListAction.CANCEL,
            page=page.page,
            player_id=0,
        ),
    )

    id_rows = [3] * (len(page.items) // 3)
    if len(page.items) % 3:
        id_rows.append(len(page.items) % 3)
    if page.total_pages > 1:
        arrows_count = int(page.has_previous) + int(page.has_next)
        builder.adjust(*id_rows, arrows_count, 1)
    else:
        builder.adjust(*id_rows, 1)
    return builder.as_markup()


def registration_match_selection_keyboard(
    player_id: int,
    matches: list[RegistrationMatchView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for position, registration_match in enumerate(matches, start=1):
        builder.button(
            text=(
                f"{position}. {registration_match.historical_player.display_name} "
                f"({registration_match.score}%)"
            ),
            callback_data=RegistrationMatchSelectionCallback(
                player_id=player_id,
                historical_player_id=registration_match.historical_player.id,
            ),
        )
    builder.button(
        text=buttons.ADMIN_REJECT,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            player_id=player_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            player_id=player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def calendar_prompt_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.CONFIRM,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.CANCEL,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.EDIT,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(2, 1)
    return builder.as_markup()


def admin_calendar_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CALENDAR_SEASONS,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.SEASONS),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_TOURNAMENTS,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.TOURNAMENTS),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=AdminCalendarCallback(action=AdminCalendarAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def manual_season_prompt_keyboard(prompt_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_CALENDAR_OPEN,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CONFIRM,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_EDIT,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.EDIT,
            prompt_id=prompt_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CALENDAR_CANCEL,
        callback_data=CalendarPromptCallback(
            action=CalendarPromptAction.CANCEL,
            prompt_id=prompt_id,
        ),
    )
    builder.adjust(2, 1)
    return builder.as_markup()
