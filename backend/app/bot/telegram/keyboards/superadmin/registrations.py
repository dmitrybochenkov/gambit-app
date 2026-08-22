from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.bot.telegram.texts.superadmin import registrations as registration_text
from app.services.dto.registrations import (
    RegistrationCandidateView,
    RegistrationReviewView,
    TournamentRegistrationCountView,
)
from app.services.pagination import Page

REGISTRATION_LIST_PAGE_SIZE = 5


class RegistrationsHubAction(StrEnum):
    USER_REQUESTS = "user_requests"
    TOURNAMENTS = "tournaments"
    BACK = "back"
    CANCEL = "cancel"


class RegistrationsHubCallback(CallbackData, prefix="registrations_hub"):
    action: RegistrationsHubAction


class TournamentRegistrationsAction(StrEnum):
    OPEN = "open"
    BACK = "back"


class TournamentRegistrationsCallback(CallbackData, prefix="tournament_registrations"):
    action: TournamentRegistrationsAction
    tournament_id: int


class RegistrationReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    BACK = "back"
    SELECT_CANDIDATE = "select_candidate"


class RegistrationReviewCallback(CallbackData, prefix="registration_review"):
    action: RegistrationReviewAction
    request_id: int
    page: int


class RegistrationCandidateSelectionCallback(CallbackData, prefix="registration_candidate"):
    request_id: int
    user_id: int
    page: int


class RegistrationCandidateConfirmAction(StrEnum):
    CONFIRM = "confirm"
    BACK = "back"
    CANCEL = "cancel"


class RegistrationCandidateConfirmCallback(CallbackData, prefix="registration_candidate_confirm"):
    action: RegistrationCandidateConfirmAction
    request_id: int
    user_id: int
    page: int


class RegistrationListAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class RegistrationListCallback(CallbackData, prefix="registration_list"):
    action: RegistrationListAction
    page: int
    request_id: int


def registrations_hub_keyboard(
    *,
    user_registration_count: int,
    tournament_registration_count: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=registration_text.user_registrations_button(user_registration_count),
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.USER_REQUESTS),
    )
    builder.button(
        text=registration_text.tournament_registrations_button(
            tournament_registration_count,
        ),
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.TOURNAMENTS),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_registrations_keyboard(
    tournaments: list[TournamentRegistrationCountView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tournament in tournaments:
        builder.button(
            text=registration_text.tournament_registration_button(tournament),
            callback_data=TournamentRegistrationsCallback(
                action=TournamentRegistrationsAction.OPEN,
                tournament_id=tournament.tournament_id,
            ),
        )
    builder.button(
        text="⬅️ Назад",
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.BACK),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def tournament_registrations_detail_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=TournamentRegistrationsCallback(
            action=TournamentRegistrationsAction.BACK,
            tournament_id=0,
        ),
    )
    builder.button(
        text="❌ Выход",
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_review_keyboard(
    request_id: int,
    page: int = 0,
    can_select_candidate: bool = False,
    can_approve: bool = True,
    approve_text: str = labels.ADMIN_APPROVE,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_select_candidate:
        builder.button(
            text="👤 Выбрать игрока",
            callback_data=RegistrationReviewCallback(
                action=RegistrationReviewAction.SELECT_CANDIDATE,
                request_id=request_id,
                page=page,
            ),
        )
    if can_approve:
        builder.button(
            text=approve_text,
            callback_data=RegistrationReviewCallback(
                action=RegistrationReviewAction.APPROVE,
                request_id=request_id,
                page=page,
            ),
        )
    builder.button(
        text=labels.ADMIN_REJECT,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            request_id=request_id,
            page=page,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.BACK,
            request_id=request_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            request_id=request_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_review_keyboard_for_review(
    review: RegistrationReviewView,
    page: int = 0,
) -> InlineKeyboardMarkup:
    if review.request.request_type != "link_existing_player":
        return registration_review_keyboard(review.request.id, page)
    if not review.candidates:
        return registration_review_keyboard(
            review.request.id,
            page,
            can_approve=False,
        )
    if len(review.candidates) == 1:
        return registration_review_keyboard(
            review.request.id,
            page,
            can_approve=True,
            approve_text="✅ Привязать",
        )
    return registration_review_keyboard(
        review.request.id,
        page,
        can_select_candidate=True,
        can_approve=False,
    )


def registration_list_keyboard(page: Page[RegistrationReviewView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for review in page.items:
        builder.button(
            text=_registration_list_button_text(review),
            callback_data=RegistrationListCallback(
                action=RegistrationListAction.OPEN,
                page=page.page,
                request_id=review.request.id,
            ),
        )

    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=RegistrationListCallback(
                    action=RegistrationListAction.PAGE,
                    page=page.previous_page,
                    request_id=0,
                ),
            )
        builder.button(
            text=f"{page.page + 1}/{page.total_pages}",
            callback_data=RegistrationListCallback(
                action=RegistrationListAction.PAGE,
                page=page.page,
                request_id=0,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=RegistrationListCallback(
                    action=RegistrationListAction.PAGE,
                    page=page.next_page,
                    request_id=0,
                ),
            )

    builder.button(
        text="⬅️ Назад",
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.BACK),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationListCallback(
            action=RegistrationListAction.CANCEL,
            page=page.page,
            request_id=0,
        ),
    )

    item_rows = [1] * len(page.items)
    if page.total_pages > 1:
        navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
        builder.adjust(*item_rows, navigation_buttons, 1, 1)
    else:
        builder.adjust(*item_rows, 1, 1)
    return builder.as_markup()


def registration_branch_empty_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад",
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.BACK),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationsHubCallback(action=RegistrationsHubAction.CANCEL),
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_candidate_selection_keyboard(
    request_id: int,
    candidates: list[RegistrationCandidateView],
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for candidate in candidates:
        builder.button(
            text=candidate.user.display_name,
            callback_data=RegistrationCandidateSelectionCallback(
                request_id=request_id,
                user_id=candidate.user.id,
                page=page,
            ),
        )
    builder.button(
        text="↩️ Назад",
        callback_data=RegistrationListCallback(
            action=RegistrationListAction.OPEN,
            request_id=request_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            request_id=request_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_candidate_confirmation_keyboard(
    request_id: int,
    user_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Привязать",
        callback_data=RegistrationCandidateConfirmCallback(
            action=RegistrationCandidateConfirmAction.CONFIRM,
            request_id=request_id,
            user_id=user_id,
            page=page,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=RegistrationCandidateConfirmCallback(
            action=RegistrationCandidateConfirmAction.BACK,
            request_id=request_id,
            user_id=user_id,
            page=page,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationCandidateConfirmCallback(
            action=RegistrationCandidateConfirmAction.CANCEL,
            request_id=request_id,
            user_id=user_id,
            page=page,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def _registration_list_button_text(review: RegistrationReviewView) -> str:
    return (
        review.request.requested_display_name or review.request.requested_link_name or "Без имени"
    )
