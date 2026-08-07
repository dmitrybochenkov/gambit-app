from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.dto.users import UserView
from app.services.pagination import Page

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


__all__ = ["PLACE_EMOJIS", "_admin_candidate_page_label", "_adjust_paged_keyboard"]
