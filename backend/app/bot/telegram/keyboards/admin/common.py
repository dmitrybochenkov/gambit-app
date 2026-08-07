# ruff: noqa: F401
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.telegram.keyboards import labels
from app.bot.telegram.texts import common as common_texts
from app.services.dto import (
    CheckInCandidateView,
    RegistrationCandidateView,
    RegistrationReviewView,
    TournamentCheckInView,
    TournamentPromptDayEditView,
    TournamentPromptView,
    TournamentResultPlayerView,
    TournamentResultsView,
    TournamentView,
    UserView,
)
from app.services.pagination import Page
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField

PLACE_EMOJIS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
}


def _admin_candidate_page_label(page: Page[UserView]) -> str:
    start = page.page * page.page_size + 1
    end = start + len(page.items) - 1
    return f"{start}-{end} из {page.total_items}"


def _adjust_paged_keyboard(
    builder: InlineKeyboardBuilder,
    page: Page,
    item_rows: list[int],
    footer_rows: list[int] | None = None,
) -> None:
    footer_rows = footer_rows or [1]
    if page.total_pages > 1:
        navigation_buttons = 1 + int(page.has_previous) + int(page.has_next)
        builder.adjust(*item_rows, navigation_buttons, *footer_rows)
    else:
        builder.adjust(*item_rows, *footer_rows)


__all__ = [name for name in globals() if not name.startswith("__")]
