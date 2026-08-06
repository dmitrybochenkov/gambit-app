# ruff: noqa: F403,F405
from app.bot.telegram.keyboards.admin.common import *  # noqa: F403


class AdminCandidateAction(StrEnum):
    OPEN = "open"
    PAGE = "page"
    CANCEL = "cancel"


class AdminCandidateCallback(CallbackData, prefix="admin_candidate"):
    action: AdminCandidateAction
    page: int
    player_id: int


class AdminAddAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"


class AdminAddCallback(CallbackData, prefix="admin_add"):
    action: AdminAddAction
    player_id: int


def admin_candidate_list_keyboard(page: Page[UserView]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in page.items:
        builder.button(
            text=f"{player.id}. {player.display_name}",
            callback_data=AdminCandidateCallback(
                action=AdminCandidateAction.OPEN,
                page=page.page,
                player_id=player.id,
            ),
        )

    if page.total_pages > 1:
        if page.has_previous:
            builder.button(
                text="⬅️",
                callback_data=AdminCandidateCallback(
                    action=AdminCandidateAction.PAGE,
                    page=page.previous_page,
                    player_id=0,
                ),
            )
        builder.button(
            text=_admin_candidate_page_label(page),
            callback_data=AdminCandidateCallback(
                action=AdminCandidateAction.PAGE,
                page=page.page,
                player_id=0,
            ),
        )
        if page.has_next:
            builder.button(
                text="➡️",
                callback_data=AdminCandidateCallback(
                    action=AdminCandidateAction.PAGE,
                    page=page.next_page,
                    player_id=0,
                ),
            )

    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminCandidateCallback(
            action=AdminCandidateAction.CANCEL,
            page=page.page,
            player_id=0,
        ),
    )

    item_rows = [1] * len(page.items)
    if page.total_pages > 1:
        navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
        builder.adjust(*item_rows, navigation_buttons, 1)
    else:
        builder.adjust(*item_rows, 1)
    return builder.as_markup()


def admin_add_confirmation_keyboard(player_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=buttons.ADMIN_ADD_CONFIRM,
        callback_data=AdminAddCallback(
            action=AdminAddAction.CONFIRM,
            player_id=player_id,
        ),
    )
    builder.button(
        text=buttons.ADMIN_CANCEL,
        callback_data=AdminAddCallback(
            action=AdminAddAction.CANCEL,
            player_id=player_id,
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
