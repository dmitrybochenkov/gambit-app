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
    if (
        parse_mode is None
        and disable_web_page_preview is None
        and _message_text_content_matches(
            message,
            text=text,
            reply_markup=reply_markup,
        )
    ):
        return False

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
    if _markup_dump(getattr(message, "reply_markup", None)) == _markup_dump(reply_markup):
        return False

    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if _is_message_not_modified_error(error):
            return False
        raise
    return True


def _message_text_content_matches(
    message: Any,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    if getattr(message, "text", None) != text:
        return False
    return _markup_dump(getattr(message, "reply_markup", None)) == _markup_dump(reply_markup)


def _markup_dump(markup: Any) -> object:
    if markup is None:
        return None
    if hasattr(markup, "model_dump"):
        return markup.model_dump(mode="json", exclude_none=True)
    return markup


def _is_message_not_modified_error(error: TelegramBadRequest) -> bool:
    return "message is not modified" in str(error).casefold()
