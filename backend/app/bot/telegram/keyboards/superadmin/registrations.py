from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.services.dto.registrations import RegistrationCandidateView, RegistrationReviewView
from app.services.pagination import Page

REGISTRATION_LIST_PAGE_SIZE = 6


class RegistrationReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    SELECT_CANDIDATE = "select_candidate"


class RegistrationReviewCallback(CallbackData, prefix="registration_review"):
    action: RegistrationReviewAction
    request_id: int


class RegistrationCandidateSelectionCallback(CallbackData, prefix="registration_candidate"):
    request_id: int
    user_id: int


class RegistrationCandidateConfirmAction(StrEnum):
    CONFIRM = "confirm"
    BACK = "back"
    CANCEL = "cancel"


class RegistrationCandidateConfirmCallback(CallbackData, prefix="registration_candidate_confirm"):
    action: RegistrationCandidateConfirmAction
    request_id: int
    user_id: int


class RegistrationListAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class RegistrationListCallback(CallbackData, prefix="registration_list"):
    action: RegistrationListAction
    page: int
    request_id: int


def registration_review_keyboard(
    request_id: int,
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
            ),
        )
    if can_approve:
        builder.button(
            text=approve_text,
            callback_data=RegistrationReviewCallback(
                action=RegistrationReviewAction.APPROVE,
                request_id=request_id,
            ),
        )
    builder.button(
        text=labels.ADMIN_REJECT,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            request_id=request_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            request_id=request_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_review_keyboard_for_review(
    review: RegistrationReviewView,
) -> InlineKeyboardMarkup:
    if review.request.request_type != "link_existing_player":
        return registration_review_keyboard(review.request.id)
    if not review.candidates:
        return registration_review_keyboard(
            review.request.id,
            can_approve=False,
        )
    if len(review.candidates) == 1:
        return registration_review_keyboard(
            review.request.id,
            can_approve=True,
            approve_text="✅ Привязать",
        )
    return registration_review_keyboard(
        review.request.id,
        can_select_candidate=True,
        can_approve=False,
    )


def registration_list_keyboard(page: Page[RegistrationReviewView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for review in page.items:
        builder.button(
            text=str(review.request.id),
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
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationListCallback(
            action=RegistrationListAction.CANCEL,
            page=page.page,
            request_id=0,
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


def registration_candidate_selection_keyboard(
    request_id: int,
    candidates: list[RegistrationCandidateView],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for candidate in candidates:
        builder.button(
            text=candidate.user.display_name,
            callback_data=RegistrationCandidateSelectionCallback(
                request_id=request_id,
                user_id=candidate.user.id,
            ),
        )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            request_id=request_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


def registration_candidate_confirmation_keyboard(
    request_id: int,
    user_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Привязать",
        callback_data=RegistrationCandidateConfirmCallback(
            action=RegistrationCandidateConfirmAction.CONFIRM,
            request_id=request_id,
            user_id=user_id,
        ),
    )
    builder.button(
        text="↩️ Назад",
        callback_data=RegistrationCandidateConfirmCallback(
            action=RegistrationCandidateConfirmAction.BACK,
            request_id=request_id,
            user_id=user_id,
        ),
    )
    builder.button(
        text=labels.ADMIN_CANCEL,
        callback_data=RegistrationCandidateConfirmCallback(
            action=RegistrationCandidateConfirmAction.CANCEL,
            request_id=request_id,
            user_id=user_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
