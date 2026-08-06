# ruff: noqa: F403,F405
from app.bot.telegram.keyboards.admin.common import *  # noqa: F403


class RegistrationReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    EDIT_NAME = "edit_name"
    SELECT_CANDIDATE = "select_candidate"


class RegistrationReviewCallback(CallbackData, prefix="registration_review"):
    action: RegistrationReviewAction
    request_id: int


class RegistrationCandidateSelectionCallback(CallbackData, prefix="registration_candidate"):
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
    can_edit_name: bool = False,
    can_select_candidate: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_select_candidate:
        builder.button(
            text="🔗 Выбрать игрока",
            callback_data=RegistrationReviewCallback(
                action=RegistrationReviewAction.SELECT_CANDIDATE,
                request_id=request_id,
            ),
        )
    if can_edit_name:
        builder.button(
            text="✏️ Изменить имя",
            callback_data=RegistrationReviewCallback(
                action=RegistrationReviewAction.EDIT_NAME,
                request_id=request_id,
            ),
        )
    builder.button(
        text=buttons.ADMIN_APPROVE,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.APPROVE,
            request_id=request_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_REJECT,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            request_id=request_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            request_id=request_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()


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
        text=buttons.ADMIN_CANCEL,
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
    for position, candidate in enumerate(candidates, start=1):
        builder.button(
            text=(f"{position}. {candidate.user.display_name} ({candidate.score}%)"),
            callback_data=RegistrationCandidateSelectionCallback(
                request_id=request_id,
                user_id=candidate.user.id,
            ),
        )
    builder.button(
        text=buttons.ADMIN_APPROVE,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.APPROVE,
            request_id=request_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_REJECT,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.REJECT,
            request_id=request_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=RegistrationReviewCallback(
            action=RegistrationReviewAction.CANCEL,
            request_id=request_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
