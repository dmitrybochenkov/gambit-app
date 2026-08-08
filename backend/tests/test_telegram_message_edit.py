from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.telegram.message_edit import (
    edit_message_if_changed,
    edit_reply_markup_if_changed,
)


def keyboard(label: str = "Открыть") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=label.casefold())],
        ]
    )


def bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendMessage(chat_id=1, text="test"),
        message=message,
    )


@pytest.mark.asyncio
async def test_edit_message_if_changed_always_calls_telegram_for_identical_local_content() -> None:
    markup = keyboard()
    message = SimpleNamespace(text="Экран", reply_markup=markup, edit_text=AsyncMock())

    changed = await edit_message_if_changed(
        message,
        text="Экран",
        reply_markup=keyboard(),
    )

    assert changed is True
    message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_message_if_changed_suppresses_message_not_modified() -> None:
    message = SimpleNamespace(
        text="Старый экран",
        reply_markup=None,
        edit_text=AsyncMock(
            side_effect=bad_request(
                "Bad Request: message is not modified: specified new message content "
                "and reply markup are exactly the same"
            )
        ),
    )

    changed = await edit_message_if_changed(message, text="Новый экран")

    assert changed is False
    message.edit_text.assert_awaited_once_with("Новый экран", reply_markup=None)


@pytest.mark.asyncio
async def test_edit_message_if_changed_reraises_other_bad_request() -> None:
    error = bad_request("Bad Request: message to edit not found")
    message = SimpleNamespace(text="Старый экран", reply_markup=None, edit_text=AsyncMock())
    message.edit_text.side_effect = error

    with pytest.raises(TelegramBadRequest) as exc_info:
        await edit_message_if_changed(message, text="Новый экран")

    assert exc_info.value is error


@pytest.mark.asyncio
async def test_edit_message_if_changed_edits_changed_text() -> None:
    message = SimpleNamespace(text="Старый экран", reply_markup=None, edit_text=AsyncMock())

    changed = await edit_message_if_changed(message, text="Новый экран")

    assert changed is True
    message.edit_text.assert_awaited_once_with("Новый экран", reply_markup=None)


@pytest.mark.asyncio
async def test_edit_message_if_changed_edits_changed_keyboard() -> None:
    message = SimpleNamespace(text="Экран", reply_markup=keyboard("Один"), edit_text=AsyncMock())

    changed = await edit_message_if_changed(
        message,
        text="Экран",
        reply_markup=keyboard("Два"),
    )

    assert changed is True
    message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_reply_markup_if_changed_suppresses_message_not_modified() -> None:
    message = SimpleNamespace(
        reply_markup=keyboard("Один"),
        edit_reply_markup=AsyncMock(
            side_effect=bad_request("Bad Request: message is not modified")
        ),
    )

    changed = await edit_reply_markup_if_changed(message, reply_markup=keyboard("Два"))

    assert changed is False
    message.edit_reply_markup.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_reply_markup_if_changed_calls_telegram_for_identical_local_markup() -> None:
    markup = keyboard("Один")
    message = SimpleNamespace(reply_markup=markup, edit_reply_markup=AsyncMock())

    changed = await edit_reply_markup_if_changed(message, reply_markup=keyboard("Один"))

    assert changed is True
    message.edit_reply_markup.assert_awaited_once()
