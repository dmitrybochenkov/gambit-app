from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import telegram_webhook as webhook_module
from app.bot.telegram import notifications, runtime
from app.bot.telegram.handlers import user as user_handlers
from app.db.models.enums import PlayerStatus


async def test_start_command_opens_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())
    service = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=None))
    monkeypatch.setattr(user_handlers, "player_service", service)

    await user_handlers.start_command(message, state)

    state.clear.assert_awaited_once()
    service.get_by_telegram_id.assert_awaited_once_with(123)
    assert message.answer.await_count == 2
    first_answer, second_answer = message.answer.await_args_list
    assert "Добро пожаловать" in first_answer.args[0]
    assert first_answer.kwargs["reply_markup"].remove_keyboard is True
    assert second_answer.args[0] == "Выбери вариант регистрации:"


async def test_registration_input_messages_are_deleted() -> None:
    bot = SimpleNamespace(delete_message=AsyncMock())
    message = SimpleNamespace(
        bot=bot,
        chat=SimpleNamespace(id=456),
        delete=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"prompt_message_id": 789}),
        update_data=AsyncMock(),
    )

    await user_handlers._delete_prompt_and_input(message, state)

    bot.delete_message.assert_awaited_once_with(chat_id=456, message_id=789)
    message.delete.assert_awaited_once()
    state.update_data.assert_awaited_once_with(prompt_message_id=None)


async def test_club_address_is_sent_to_active_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    player = SimpleNamespace(status=PlayerStatus.ACTIVE)
    service = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=player))
    monkeypatch.setattr(user_handlers, "player_service", service)

    await user_handlers.show_club_address(message)

    service.get_by_telegram_id.assert_awaited_once_with(123)
    message.answer.assert_awaited_once_with("Адрес: г. Орехово-Зуево, д. 1")


async def test_pending_registration_notifies_admins(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = SimpleNamespace(send_message=AsyncMock())
    player = SimpleNamespace(
        id=10,
        telegram_id=200,
        full_name="Игрок Второй",
        nickname="Ace",
    )
    admins = [
        SimpleNamespace(telegram_id=100),
        SimpleNamespace(telegram_id=101),
    ]
    service = SimpleNamespace(get_active_admins=AsyncMock(return_value=admins))
    monkeypatch.setattr(notifications, "player_service", service)

    await notifications.notify_admins_about_registration(bot, player)

    service.get_active_admins.assert_awaited_once()
    assert bot.send_message.await_count == 2
    assert bot.send_message.await_args_list[0].kwargs["chat_id"] == 100
    assert bot.send_message.await_args_list[1].kwargs["chat_id"] == 101


async def test_webhook_rejects_invalid_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhook_module, "telegram_bot", object())
    monkeypatch.setattr(webhook_module.settings, "telegram_webhook_secret", "secret")

    with pytest.raises(HTTPException) as error:
        await webhook_module.telegram_webhook(
            payload={"update_id": 1},
            x_telegram_bot_api_secret_token="wrong",
        )

    assert error.value.status_code == 403


async def test_webhook_feeds_update(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = object()
    feed_raw_update = AsyncMock()
    monkeypatch.setattr(webhook_module, "telegram_bot", bot)
    monkeypatch.setattr(webhook_module.telegram_dispatcher, "feed_raw_update", feed_raw_update)
    monkeypatch.setattr(webhook_module.settings, "telegram_webhook_secret", "secret")

    response = await webhook_module.telegram_webhook(
        payload={"update_id": 1},
        x_telegram_bot_api_secret_token="secret",
    )

    assert response == {"ok": True}
    feed_raw_update.assert_awaited_once_with(bot, {"update_id": 1})


async def test_setup_webhook_uses_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = SimpleNamespace(set_webhook=AsyncMock())
    monkeypatch.setattr(runtime, "telegram_bot", bot)
    monkeypatch.setattr(runtime.settings, "public_base_url", "https://gambit.example/")
    monkeypatch.setattr(runtime.settings, "telegram_webhook_secret", "secret")

    await runtime.setup_telegram_webhook()

    bot.set_webhook.assert_awaited_once_with(
        url="https://gambit.example/webhooks/tg",
        secret_token="secret",
        drop_pending_updates=True,
        allowed_updates=["callback_query", "message"],
    )
