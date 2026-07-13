from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import telegram_webhook as webhook_module
from app.bot.telegram import notifications, runtime
from app.bot.telegram.handlers import user as user_handlers
from app.db.models.enums import PlayerStatus
from app.services.profile_service import ProfileKind
from app.services.rating_service import RatingKind


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
    message.answer.assert_awaited_once_with(
        "📍 Орехово-Зуево, ул. Ленина, 105\n"
        "🏆 Играем исключительно на рейтинг и спортивный интерес."
    )


async def test_rating_button_shows_four_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    player = SimpleNamespace(status=PlayerStatus.ACTIVE)
    service = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=player))
    monkeypatch.setattr(user_handlers, "player_service", service)

    await user_handlers.show_rating_menu(message)

    answer = message.answer.await_args
    assert answer.args[0] == "Какой рейтинг ты хочешь посмотреть?"
    buttons = [
        row[0].text
        for row in answer.kwargs["reply_markup"].inline_keyboard
    ]
    assert buttons == [
        "Текущий сезон",
        "За все время",
        "Нокауты",
        "Нокауты за время",
    ]


async def test_rating_callback_sends_selected_rating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = SimpleNamespace(status=PlayerStatus.ACTIVE)
    player_service = SimpleNamespace(
        get_by_telegram_id=AsyncMock(return_value=player)
    )
    rating_service = SimpleNamespace(
        get_rating=AsyncMock(return_value=("Рейтинг — текущий сезон", []))
    )
    monkeypatch.setattr(user_handlers, "player_service", player_service)
    monkeypatch.setattr(user_handlers, "rating_service", rating_service)
    message = SimpleNamespace(answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(kind=RatingKind.CURRENT_SEASON)

    await user_handlers.show_rating(callback, callback_data)

    rating_service.get_rating.assert_awaited_once_with(RatingKind.CURRENT_SEASON)
    message.answer.assert_awaited_once_with(
        "Рейтинг — текущий сезон\n\nВ рейтинге пока нет данных."
    )


async def test_profile_button_shows_two_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    player = SimpleNamespace(status=PlayerStatus.ACTIVE)
    service = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=player))
    monkeypatch.setattr(user_handlers, "player_service", service)

    await user_handlers.show_profile_menu(message)

    answer = message.answer.await_args
    assert answer.args[0] == "За какой период ты хочешь посмотреть свои достижения?"
    buttons = [
        row[0].text
        for row in answer.kwargs["reply_markup"].inline_keyboard
    ]
    assert buttons == ["За текущий сезон", "За все время"]


async def test_profile_callback_sends_selected_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = SimpleNamespace(status=PlayerStatus.ACTIVE)
    player_service = SimpleNamespace(
        get_by_telegram_id=AsyncMock(return_value=player)
    )
    profile_service = SimpleNamespace(
        get_profile=AsyncMock(return_value=("Твой профиль — текущий сезон", None))
    )
    monkeypatch.setattr(user_handlers, "player_service", player_service)
    monkeypatch.setattr(user_handlers, "profile_service", profile_service)
    message = SimpleNamespace(answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(kind=ProfileKind.CURRENT_SEASON)

    await user_handlers.show_profile(callback, callback_data)

    profile_service.get_profile.assert_awaited_once_with(
        telegram_id=123,
        kind=ProfileKind.CURRENT_SEASON,
    )
    message.answer.assert_awaited_once_with(
        "Твой профиль — текущий сезон\n\nПрофиль не найден. Нажми /start."
    )


async def test_registration_button_shows_upcoming_tournaments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    player = SimpleNamespace(status=PlayerStatus.ACTIVE)
    tournament = SimpleNamespace(
        id=7,
        date=date(2026, 7, 8),
        type=1,
    )
    player_service = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=player))
    tournament_service = SimpleNamespace(
        get_upcoming_schedule=AsyncMock(return_value=[tournament])
    )
    state = SimpleNamespace(update_data=AsyncMock())
    monkeypatch.setattr(user_handlers, "player_service", player_service)
    monkeypatch.setattr(user_handlers, "tournament_service", tournament_service)

    await user_handlers.show_tournaments_for_registration(message, state)

    answer = message.answer.await_args
    assert answer.args[0] == (
        "Выбери даты турниров, на которые хочешь записаться, "
        "и нажми «Подтвердить»."
    )
    button = answer.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Среда, 8 июля — Турнир 1"
    assert button.callback_data == "tournament_register:7"
    controls = answer.kwargs["reply_markup"].inline_keyboard[1]
    assert [button.text for button in controls] == ["Подтвердить", "Отмена"]
    state.update_data.assert_awaited_once_with(tournament_registration_selection=[])


async def test_multiple_tournament_registration_sends_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournaments = [
        SimpleNamespace(id=7, date=date(2026, 7, 8), type=1),
        SimpleNamespace(id=8, date=date(2026, 7, 9), type=2),
    ]
    service = SimpleNamespace(
        register_player_for_tournaments=AsyncMock(return_value=tournaments)
    )
    monkeypatch.setattr(user_handlers, "tournament_service", service)
    message = SimpleNamespace(
        edit_reply_markup=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={"tournament_registration_selection": [7, 8]}
        ),
        update_data=AsyncMock(),
    )

    await user_handlers.confirm_tournament_registration(callback, state)

    service.register_player_for_tournaments.assert_awaited_once_with(
        telegram_id=123,
        tournament_ids=[7, 8],
    )
    message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    confirmation = message.answer.await_args.args[0]
    assert "Вы записались на турниры:" in confirmation
    assert "Среда, 8 июля — Турнир 1" in confirmation
    assert "Четверг, 9 июля — Турнир 2" in confirmation
    assert "вы отмените запись заранее" in confirmation


async def test_tournament_registration_selection_can_be_cancelled() -> None:
    message = SimpleNamespace(
        edit_reply_markup=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    state = SimpleNamespace(update_data=AsyncMock())

    await user_handlers.cancel_tournament_registration_selection(callback, state)

    state.update_data.assert_awaited_once_with(tournament_registration_selection=[])
    message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    message.answer.assert_awaited_once_with("Запись на турнир(ы) отменена.")


async def test_cancellation_button_reports_when_player_has_no_registrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_player_upcoming_registrations=AsyncMock(return_value=[])
    )
    monkeypatch.setattr(user_handlers, "tournament_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(update_data=AsyncMock())

    await user_handlers.show_tournaments_for_cancellation(message, state)

    message.answer.assert_awaited_once_with("Ты не записан ни на один турнир.")
    state.update_data.assert_not_awaited()


async def test_multiple_tournament_cancellation_sends_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournaments = [
        SimpleNamespace(id=7, date=date(2026, 7, 8), type=1),
        SimpleNamespace(id=8, date=date(2026, 7, 9), type=2),
    ]
    service = SimpleNamespace(
        cancel_player_tournament_registrations=AsyncMock(
            return_value=tournaments
        )
    )
    monkeypatch.setattr(user_handlers, "tournament_service", service)
    message = SimpleNamespace(
        edit_reply_markup=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={"tournament_cancellation_selection": [7, 8]}
        ),
        update_data=AsyncMock(),
    )

    await user_handlers.confirm_tournament_cancellation(callback, state)

    service.cancel_player_tournament_registrations.assert_awaited_once_with(
        telegram_id=123,
        tournament_ids=[7, 8],
    )
    confirmation = message.answer.await_args.args[0]
    assert "Ты отменил запись на турниры:" in confirmation
    assert "Среда, 8 июля — Турнир 1" in confirmation
    assert "Четверг, 9 июля — Турнир 2" in confirmation


async def test_tournament_cancellation_selection_can_be_cancelled() -> None:
    message = SimpleNamespace(
        edit_reply_markup=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    state = SimpleNamespace(update_data=AsyncMock())

    await user_handlers.cancel_tournament_cancellation_selection(callback, state)

    state.update_data.assert_awaited_once_with(tournament_cancellation_selection=[])
    message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    message.answer.assert_awaited_once_with("Отмена записи на турниры отменена.")


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
    service = SimpleNamespace(
        get_active_admins=AsyncMock(return_value=admins),
        get_registration_matches=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(notifications, "player_service", service)

    await notifications.notify_admins_about_registration(bot, player)

    service.get_active_admins.assert_awaited_once()
    service.get_registration_matches.assert_awaited_once_with(10)
    assert bot.send_message.await_count == 2
    assert bot.send_message.await_args_list[0].kwargs["chat_id"] == 100
    assert bot.send_message.await_args_list[1].kwargs["chat_id"] == 101
    assert "Telegram ID" not in bot.send_message.await_args_list[0].kwargs["text"]


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
