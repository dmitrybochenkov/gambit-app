from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup


async def edit_message_if_changed(
    message: Any,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool | None = None,
) -> bool:
    """Edit message text, returning False for idempotent no-op updates."""
    kwargs: dict[str, Any] = {"reply_markup": reply_markup}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if disable_web_page_preview is not None:
        kwargs["disable_web_page_preview"] = disable_web_page_preview

    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as error:
        if _is_message_not_modified_error(error):
            return False
        raise
    return True


async def edit_reply_markup_if_changed(
    message: Any,
    *,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    """Edit only reply markup, returning False for idempotent no-op updates."""
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if _is_message_not_modified_error(error):
            return False
        raise
    return True


async def edit_message_reply_markup_by_id_if_changed(
    bot: Any,
    *,
    chat_id: int,
    message_id: int,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    """Edit reply markup by message id, returning False for idempotent no-op updates."""
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as error:
        if _is_message_not_modified_error(error):
            return False
        raise
    return True


def _is_message_not_modified_error(error: TelegramBadRequest) -> bool:
    return "message is not modified" in str(error).casefold()
