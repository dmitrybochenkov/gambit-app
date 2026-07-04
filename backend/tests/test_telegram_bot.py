from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import telegram_webhook as webhook_module
from app.bot.telegram import runtime
from app.bot.telegram.handlers import start_command


async def test_start_command_answers_working() -> None:
    message = SimpleNamespace(answer=AsyncMock())

    await start_command(message)

    message.answer.assert_awaited_once_with("Работает")


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
        allowed_updates=["message"],
    )
