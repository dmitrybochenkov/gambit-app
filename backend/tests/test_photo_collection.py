from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage

from app.bot.telegram.keyboards.admin.results import admin_result_photo_collect_keyboard
from app.bot.telegram.photo_collection import (
    PhotoControlContext,
    refresh_photo_control_message,
    send_media_then_restore_control,
)


class MutablePhotoState:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    async def get_data(self) -> dict[str, object]:
        return self.data

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


async def test_refresh_photo_control_message_sends_new_control_after_delete_failure() -> None:
    message = SimpleNamespace(
        chat=SimpleNamespace(id=100),
        bot=SimpleNamespace(
            delete_message=AsyncMock(
                side_effect=TelegramBadRequest(
                    method=DeleteMessage(chat_id=100, message_id=10),
                    message="message to delete not found",
                )
            )
        ),
        answer=AsyncMock(return_value=SimpleNamespace(message_id=77)),
    )
    state = MutablePhotoState({"photo_control_message_id": 10})
    context = PhotoControlContext(
        tournament_id=1,
        control_message_id_key="photo_control_message_id",
        reply_markup=admin_result_photo_collect_keyboard(1),
    )

    await refresh_photo_control_message(
        message,
        state,  # type: ignore[arg-type]
        context,
        photo_count=4,
    )

    message.bot.delete_message.assert_awaited_once_with(chat_id=100, message_id=10)
    message.answer.assert_awaited_once()
    assert "Загружено фото: 4" in message.answer.await_args.args[0]
    assert state.data["photo_control_message_id"] == 77


async def test_send_media_then_restore_control_restores_after_media_failure() -> None:
    message = SimpleNamespace(
        chat=SimpleNamespace(id=100),
        bot=SimpleNamespace(delete_message=AsyncMock()),
    )
    state = MutablePhotoState({"photo_control_message_id": 10})
    context = PhotoControlContext(
        tournament_id=1,
        control_message_id_key="photo_control_message_id",
        reply_markup=admin_result_photo_collect_keyboard(1),
    )
    restore_control = AsyncMock(return_value=88)

    async def broken_media_sender() -> None:
        raise RuntimeError("telegram media failed")

    try:
        await send_media_then_restore_control(
            message,
            state,  # type: ignore[arg-type]
            context,
            media_sender=broken_media_sender,
            restore_control=restore_control,
        )
    except RuntimeError as exc:
        assert str(exc) == "telegram media failed"
    else:
        raise AssertionError("media failure must be re-raised")

    message.bot.delete_message.assert_awaited_once_with(chat_id=100, message_id=10)
    restore_control.assert_awaited_once()
    assert state.data["photo_control_message_id"] == 88
