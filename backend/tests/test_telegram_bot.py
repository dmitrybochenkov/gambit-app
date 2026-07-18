from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import telegram_webhook as webhook_module
from app.bot.telegram import keyboards, notifications, runtime
from app.bot.telegram.handlers import admin as admin_handlers
from app.bot.telegram.handlers import user as user_handlers
from app.services.calendar_service import CalendarPromptInvalidPayloadError
from app.services.dto import (
    AdminPanelView,
    AdminPromptView,
    PlayerRoleView,
    PlayerStatusView,
    PlayerView,
    PointsRatingView,
    RatingResultView,
    RegistrationMatchView,
    RegistrationNotificationView,
    RegistrationReviewResultView,
    RegistrationReviewView,
    TournamentView,
)
from app.services.player_service import AdminAccessDeniedError
from app.services.profile_service import ProfileKind
from app.services.rating_service import RatingKind


def active_player() -> PlayerView:
    return PlayerView(
        id=1,
        telegram_id=123,
        display_name="Игрок Первый",
        full_name="Игрок Первый",
        nickname=None,
        status=PlayerStatusView.ACTIVE,
        role=PlayerRoleView.USER,
    )


def admin_player(
    player_id: int,
    telegram_id: int,
    role: PlayerRoleView = PlayerRoleView.ADMIN,
) -> PlayerView:
    return PlayerView(
        id=player_id,
        telegram_id=telegram_id,
        display_name=f"Админ {player_id}",
        full_name=f"Админ {player_id}",
        nickname=None,
        status=PlayerStatusView.ACTIVE,
        role=role,
    )


def tournament_view(
    tournament_id: int,
    tournament_date: date,
    tournament_type_id: int,
) -> TournamentView:
    return TournamentView(
        id=tournament_id,
        date=tournament_date,
        capacity=30,
        tournament_type_id=tournament_type_id,
        tournament_type_name=None,
    )


def keyboard_texts(reply_markup: object) -> list[str]:
    return [button.text for row in reply_markup.keyboard for button in row]


def registration_match(player_id: int, score: int) -> RegistrationMatchView:
    return RegistrationMatchView(
        score=score,
        reason=f"имя похоже на {score}%",
        historical_player=PlayerView(
            id=player_id,
            telegram_id=-player_id,
            display_name=f"Исторический {player_id}",
            full_name=f"Исторический {player_id}",
            nickname=None,
            status=PlayerStatusView.ACTIVE,
            role=PlayerRoleView.USER,
        ),
    )


def registration_review(player_id: int) -> RegistrationReviewView:
    return RegistrationReviewView(
        player=PlayerView(
            id=player_id,
            telegram_id=1000 + player_id,
            display_name=f"Игрок {player_id}",
            full_name=f"Игрок {player_id}",
            nickname=None,
            status=PlayerStatusView.PENDING,
            role=PlayerRoleView.USER,
        ),
        matches=[],
    )


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


async def test_start_command_shows_admin_keyboard_for_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())
    service = SimpleNamespace(
        get_by_telegram_id=AsyncMock(return_value=admin_player(1, 123))
    )
    monkeypatch.setattr(user_handlers, "player_service", service)

    await user_handlers.start_command(message, state)

    state.clear.assert_awaited_once()
    service.get_by_telegram_id.assert_awaited_once_with(123)
    assert message.answer.await_count == 1
    reply_markup = message.answer.await_args.kwargs["reply_markup"]
    assert keyboards.MAIN_ADMIN in keyboard_texts(reply_markup)


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
    player = active_player()
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
    player = active_player()
    service = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=player))
    monkeypatch.setattr(user_handlers, "player_service", service)

    await user_handlers.show_rating_menu(message)

    answer = message.answer.await_args
    assert answer.args[0] == "Какой рейтинг ты хочешь посмотреть?"
    buttons = [
        button.text
        for row in answer.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == [
        "🏆 Текущий сезон",
        "🏆⏳ За все время",
        "💥 Нокауты",
        "💥⏳ Нокауты за все время",
        "❌ Отмена",
    ]


async def test_rating_callback_edits_selected_rating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rating_service = SimpleNamespace(
        get_rating_for_player=AsyncMock(
            return_value=RatingResultView(
                title="Рейтинг — текущий сезон",
                rows=[
                    PointsRatingView(
                        player_id=1,
                        display_name="Игрок Первый",
                        total_points=Decimal("120"),
                        tournaments_count=3,
                    )
                ],
                current_player_id=1,
            )
        )
    )
    monkeypatch.setattr(user_handlers, "rating_service", rating_service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(kind=RatingKind.CURRENT_SEASON, page=0)

    await user_handlers.show_rating(callback, callback_data)

    rating_service.get_rating_for_player.assert_awaited_once_with(
        telegram_id=123,
        kind=RatingKind.CURRENT_SEASON,
    )
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == (
        "Рейтинг — текущий сезон\n\n"
        "🥇 *Игрок Первый* — 120 очков (турниров: 3)"
    )
    assert message.edit_text.await_args.kwargs["parse_mode"] == "Markdown"
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["1-1 из 1", "❌ Закрыть рейтинг"]


async def test_rating_menu_cancel_deletes_message() -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    callback_data = SimpleNamespace(action=keyboards.RatingCancelAction.CANCEL)

    await user_handlers.cancel_rating(callback, callback_data)

    callback.answer.assert_awaited_once_with("Отмена")
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with("Отмена")


async def test_rating_close_deletes_message() -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    callback_data = SimpleNamespace(action=keyboards.RatingCancelAction.CLOSE)

    await user_handlers.cancel_rating(callback, callback_data)

    callback.answer.assert_awaited_once_with("Рейтинг закрыт")
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with("Рейтинг закрыт")


async def test_profile_button_shows_two_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    player = active_player()
    service = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=player))
    monkeypatch.setattr(user_handlers, "player_service", service)

    await user_handlers.show_profile_menu(message)

    answer = message.answer.await_args
    assert answer.args[0] == "За какой период ты хочешь посмотреть свои достижения?"
    buttons = [
        button.text
        for row in answer.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["🏆 За текущий сезон", "⏳ За все время", "❌ Отмена"]


async def test_profile_callback_sends_selected_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_service = SimpleNamespace(
        get_profile_for_player=AsyncMock(
            return_value=("Твой профиль — текущий сезон", None)
        )
    )
    monkeypatch.setattr(user_handlers, "profile_service", profile_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(kind=ProfileKind.CURRENT_SEASON)

    await user_handlers.show_profile(callback, callback_data)

    profile_service.get_profile_for_player.assert_awaited_once_with(
        telegram_id=123,
        kind=ProfileKind.CURRENT_SEASON,
    )
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with(
        "Твой профиль — текущий сезон\n\nПрофиль не найден. Нажми /start."
    )


async def test_profile_cancel_deletes_message_and_sends_confirmation() -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())

    await user_handlers.cancel_profile(callback)

    callback.answer.assert_awaited_once_with("Отмена")
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with("Отмена")


async def test_registration_button_shows_upcoming_tournaments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    tournament = tournament_view(7, date(2026, 7, 8), 1)
    tournament_service = SimpleNamespace(
        get_registration_options_for_player=AsyncMock(return_value=[tournament])
    )
    state = SimpleNamespace(update_data=AsyncMock())
    monkeypatch.setattr(user_handlers, "tournament_service", tournament_service)

    await user_handlers.show_tournaments_for_registration(message, state)

    answer = message.answer.await_args
    assert answer.args[0] == "Выбери турниры, на которые хочешь записаться."
    button = answer.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Среда, 8 июля — Турнир 1"
    assert button.callback_data == "tournament_register:select:0:7"
    controls = answer.kwargs["reply_markup"].inline_keyboard[1]
    assert [button.text for button in controls] == ["✅ Подтвердить", "❌ Отмена"]
    state.update_data.assert_awaited_once_with(tournament_registration_selection=[])


async def test_tournament_registration_list_is_paginated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    tournaments = [
        tournament_view(tournament_id, date(2026, 7, tournament_id), 1)
        for tournament_id in range(1, 8)
    ]
    tournament_service = SimpleNamespace(
        get_registration_options_for_player=AsyncMock(return_value=tournaments)
    )
    state = SimpleNamespace(update_data=AsyncMock())
    monkeypatch.setattr(user_handlers, "tournament_service", tournament_service)

    await user_handlers.show_tournaments_for_registration(message, state)

    rows = message.answer.await_args.kwargs["reply_markup"].inline_keyboard
    assert len(rows[:6]) == 6
    assert [button.text for button in rows[6]] == ["1-6 из 7", "➡️"]
    assert rows[6][1].callback_data == "tournament_register:page:1:0"
    assert [button.text for button in rows[7]] == ["✅ Подтвердить", "❌ Отмена"]


async def test_tournament_registration_page_callback_keeps_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournaments = [
        tournament_view(tournament_id, date(2026, 7, tournament_id), 1)
        for tournament_id in range(1, 8)
    ]
    service = SimpleNamespace(
        get_registration_options_for_player=AsyncMock(return_value=tournaments)
    )
    monkeypatch.setattr(user_handlers, "tournament_service", service)
    message = SimpleNamespace(edit_reply_markup=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.TournamentListAction.PAGE,
        page=1,
        tournament_id=0,
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"tournament_registration_selection": [1]}),
        update_data=AsyncMock(),
    )

    await user_handlers.register_for_tournament(callback, callback_data, state)

    state.update_data.assert_awaited_once_with(tournament_registration_selection=[1])
    callback.answer.assert_awaited_once_with()
    rows = message.edit_reply_markup.await_args.kwargs["reply_markup"].inline_keyboard
    assert rows[0][0].text == "Вторник, 7 июля — Турнир 1"
    assert [button.text for button in rows[1]] == ["⬅️", "7-7 из 7"]


async def test_multiple_tournament_registration_sends_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournaments = [
        tournament_view(7, date(2026, 7, 8), 1),
        tournament_view(8, date(2026, 7, 9), 2),
    ]
    service = SimpleNamespace(
        register_player_for_tournaments=AsyncMock(return_value=tournaments)
    )
    monkeypatch.setattr(user_handlers, "tournament_service", service)
    message = SimpleNamespace(
        delete=AsyncMock(),
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
    message.delete.assert_awaited_once_with()
    confirmation = message.answer.await_args.args[0]
    assert "Ты записан на турниры:" in confirmation
    assert "Среда, 8 июля — Турнир 1" in confirmation
    assert "Четверг, 9 июля — Турнир 2" in confirmation
    assert "вы отмените запись заранее" in confirmation


async def test_tournament_registration_selection_can_be_cancelled() -> None:
    message = SimpleNamespace(
        delete=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    state = SimpleNamespace(update_data=AsyncMock())

    await user_handlers.cancel_tournament_registration_selection(callback, state)

    state.update_data.assert_awaited_once_with(tournament_registration_selection=[])
    callback.answer.assert_awaited_once_with("Отмена")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with("Отмена")


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
        tournament_view(7, date(2026, 7, 8), 1),
        tournament_view(8, date(2026, 7, 9), 2),
    ]
    service = SimpleNamespace(
        cancel_player_tournament_registrations=AsyncMock(
            return_value=tournaments
        )
    )
    monkeypatch.setattr(user_handlers, "tournament_service", service)
    message = SimpleNamespace(
        delete=AsyncMock(),
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
    message.delete.assert_awaited_once_with()
    confirmation = message.answer.await_args.args[0]
    assert "Ты отменил запись на турниры:" in confirmation
    assert "Среда, 8 июля — Турнир 1" in confirmation
    assert "Четверг, 9 июля — Турнир 2" in confirmation


async def test_tournament_cancellation_selection_can_be_cancelled() -> None:
    message = SimpleNamespace(
        delete=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    state = SimpleNamespace(update_data=AsyncMock())

    await user_handlers.cancel_tournament_cancellation_selection(callback, state)

    state.update_data.assert_awaited_once_with(tournament_cancellation_selection=[])
    callback.answer.assert_awaited_once_with("Отмена")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with("Отмена")


async def test_pending_registration_notifies_admins(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = SimpleNamespace(send_message=AsyncMock())
    player = PlayerView(
        id=10,
        telegram_id=200,
        display_name="Игрок Второй (Ace)",
        full_name="Игрок Второй",
        nickname="Ace",
        status=PlayerStatusView.PENDING,
        role=PlayerRoleView.USER,
    )
    admins = [
        PlayerView(
            id=1,
            telegram_id=100,
            display_name="Админ Первый",
            full_name="Админ Первый",
            nickname=None,
            status=PlayerStatusView.ACTIVE,
            role=PlayerRoleView.SUPERADMIN,
        ),
        PlayerView(
            id=2,
            telegram_id=101,
            display_name="Админ Второй",
            full_name="Админ Второй",
            nickname=None,
            status=PlayerStatusView.ACTIVE,
            role=PlayerRoleView.ADMIN,
        ),
    ]
    service = SimpleNamespace(
        get_registration_notification=AsyncMock(
            return_value=RegistrationNotificationView(
                player=player,
                admins=admins,
                matches=[],
            )
        ),
    )
    monkeypatch.setattr(notifications, "player_service", service)

    await notifications.notify_admins_about_registration(bot, player)

    service.get_registration_notification.assert_awaited_once_with(10)
    assert bot.send_message.await_count == 2
    assert bot.send_message.await_args_list[0].kwargs["chat_id"] == 100
    assert bot.send_message.await_args_list[1].kwargs["chat_id"] == 101
    assert "Telegram ID" not in bot.send_message.await_args_list[0].kwargs["text"]


async def test_admin_panel_entry_sends_admin_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(
            return_value=AdminPanelView(admin=admin, reviews=[])
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == "Добро пожаловать в админ-панель."
    assert keyboard_texts(answer.kwargs["reply_markup"]) == [
        "📝 Заявки на регистрацию",
        "🗓 Календарь",
        "➕ Добавить админа",
        "⬅️ Выход",
    ]


async def test_admin_calendar_button_shows_inline_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    service = SimpleNamespace(
        require_superadmin=AsyncMock(return_value=admin)
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_admin_calendar(message)

    service.require_superadmin.assert_awaited_once_with(100)
    answer = message.answer.await_args
    assert answer.args[0] == "Меню для создания сезонов и турниров в базе данных."
    buttons = [
        button.text
        for row in answer.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["⏳ Сезоны", "🏆 Турниры", "❌ Отмена"]
    assert [len(row) for row in answer.kwargs["reply_markup"].inline_keyboard] == [
        1,
        1,
        1,
    ]


async def test_admin_calendar_seasons_callback_sends_manual_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    player_service = SimpleNamespace(
        require_superadmin=AsyncMock(return_value=admin)
    )
    calendar_service = SimpleNamespace(
        get_or_create_manual_season_prompt=AsyncMock(
            return_value=AdminPromptView(
                id=7,
                kind="season_proposal",
                payload=(
                    '{"name":"Осень 2026",'
                    '"starts_at":"2026-09-01",'
                    '"ends_at":"2026-11-30"}'
                ),
                status="pending",
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", player_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    message = SimpleNamespace(
        delete=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(action=keyboards.AdminCalendarAction.SEASONS)

    await admin_handlers.select_admin_calendar_section(callback, callback_data)

    player_service.require_superadmin.assert_awaited_once_with(100)
    calendar_service.get_or_create_manual_season_prompt.assert_awaited_once_with()
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == (
        "Будет создан новый сезон:\n"
        "Осень 2026\n"
        "Период: 1.09.2026 — 30.11.2026"
    )
    buttons = [
        button.text
        for row in answer.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["✅ Создать", "✏️ Изменить", "❌ Отмена"]


async def test_admin_calendar_tournaments_callback_sends_detailed_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    player_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        get_or_create_manual_tournaments_prompt=AsyncMock(
            return_value=AdminPromptView(
                id=8,
                kind="tournaments_proposal",
                payload=(
                    '{"tournaments":[{'
                    '"date":"2026-07-22",'
                    '"tournament_type_id":1,'
                    '"tournament_type_name":"Баунти турнир",'
                    '"entry_fee":600,'
                    '"entry_stack":20000,'
                    '"addon_fee":800,'
                    '"addon_stack":125000,'
                    '"rebuys":[{"fee":600,"stack":30000}],'
                    '"capacity":30'
                    "}]} "
                ),
                status="pending",
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", player_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(action=keyboards.AdminCalendarAction.TOURNAMENTS)

    await admin_handlers.select_admin_calendar_section(callback, callback_data)

    calendar_service.get_or_create_manual_tournaments_prompt.assert_awaited_once_with()
    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == (
        "Будут созданы турниры на ближайшую неделю:\n\n"
        "• Среда, 22 июля — Баунти турнир\n"
        "Вход:\n"
        "600 ₽ — 20 000 фишек\n"
        "Ребаи:\n"
        "600 ₽\n"
        "30 000 фишек\n"
        "Аддон:\n"
        "800 ₽ — 125 000 фишек"
    )
    buttons = [
        button.text
        for row in answer.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["✅ Создать", "✏️ Изменить", "❌ Отмена"]


async def test_admin_calendar_denies_regular_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        require_superadmin=AsyncMock(side_effect=AdminAccessDeniedError)
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_admin_calendar(message)

    service.require_superadmin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once_with("Недостаточно прав.")


async def test_admin_calendar_prompt_denies_regular_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        require_superadmin=AsyncMock(side_effect=AdminAccessDeniedError)
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.CalendarPromptAction.CONFIRM,
        prompt_id=7,
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.review_calendar_prompt(callback, callback_data, state)

    service.require_superadmin.assert_awaited_once_with(100)
    state.clear.assert_not_awaited()
    callback.answer.assert_awaited_once_with("Недостаточно прав.", show_alert=True)


async def test_manual_season_confirm_deletes_prompt_and_sends_created_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    player_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        resolve_prompt=AsyncMock(
            return_value=AdminPromptView(
                id=7,
                kind="season_proposal",
                payload=(
                    '{"name":"Осень 2026",'
                    '"starts_at":"2026-09-01",'
                    '"ends_at":"2026-11-30"}'
                ),
                status="confirmed",
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", player_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    message = SimpleNamespace(
        text=(
            "Будет создан новый сезон:\n"
            "Осень 2026\n"
            "Период: 1.09.2026 — 30.11.2026"
        ),
        delete=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Dima Bochenkov"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.CalendarPromptAction.CONFIRM,
        prompt_id=7,
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.review_calendar_prompt(callback, callback_data, state)

    calendar_service.resolve_prompt.assert_awaited_once()
    state.clear.assert_awaited_once()
    callback.answer.assert_awaited_once_with("Сезон создан.")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with(
        "Создан новый сезон:\n"
        "Осень 2026\n"
        "Период: 1.09.2026 — 30.11.2026"
    )


async def test_season_edit_button_opens_field_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    player_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        get_prompt=AsyncMock(
            return_value=AdminPromptView(
                id=7,
                kind="season_proposal",
                payload=(
                    '{"name":"Осень 2026",'
                    '"starts_at":"2026-09-01",'
                    '"ends_at":"2026-11-30"}'
                ),
                status="pending",
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", player_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.CalendarPromptAction.EDIT,
        prompt_id=7,
    )

    await admin_handlers.review_calendar_prompt(callback, callback_data, state)

    player_service.require_superadmin.assert_awaited_once_with(100)
    calendar_service.get_prompt.assert_awaited_once_with(7)
    state.clear.assert_awaited_once()
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "Что меняем?"
    buttons = [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == [
        "✏️ Название",
        "📅 Дата начала",
        "🏁 Дата окончания",
        "❌ Отмена",
    ]


async def test_tournament_edit_button_opens_day_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    player_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        get_prompt=AsyncMock(
            return_value=AdminPromptView(
                id=8,
                kind="tournaments_proposal",
                payload=(
                    '{"tournaments":[{'
                    '"date":"2026-07-22",'
                    '"tournament_type_id":1,'
                    '"tournament_type_name":"Баунти турнир",'
                    '"entry_fee":600,'
                    '"entry_stack":20000,'
                    '"addon_fee":800,'
                    '"addon_stack":125000,'
                    '"rebuys":[],'
                    '"capacity":30'
                    "}]} "
                ),
                status="pending",
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", player_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.CalendarPromptAction.EDIT,
        prompt_id=8,
    )

    await admin_handlers.review_calendar_prompt(callback, callback_data, state)

    calendar_service.get_prompt.assert_awaited_once_with(8)
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0] == "Что меняем?"
    buttons = [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["Среда, 22.07.2026", "❌ Отмена"]


async def test_season_edit_field_prompts_for_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    monkeypatch.setattr(admin_handlers, "player_service", service)
    state = SimpleNamespace(set_state=AsyncMock(), update_data=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.SeasonEditAction.STARTS_AT,
        prompt_id=7,
    )

    await admin_handlers.select_season_edit_field(callback, callback_data, state)

    service.require_superadmin.assert_awaited_once_with(100)
    message.delete.assert_awaited_once_with()
    state.set_state.assert_awaited_once()
    state.update_data.assert_awaited_once_with(
        season_prompt_id=7,
        season_edit_field=keyboards.SeasonEditAction.STARTS_AT.value,
    )
    message.answer.assert_awaited_once_with(
        "Введи дату начала в формате 1.09.2026."
    )


async def test_season_edit_value_updates_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    player_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    prompt = AdminPromptView(
        id=7,
        kind="season_proposal",
        payload=(
            '{"name":"Осень 2026",'
            '"starts_at":"2026-09-02",'
            '"ends_at":"2026-11-30"}'
        ),
        status="pending",
    )
    calendar_service = SimpleNamespace(update_season_prompt=AsyncMock(return_value=prompt))
    monkeypatch.setattr(admin_handlers, "player_service", player_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                "season_prompt_id": 7,
                "season_edit_field": keyboards.SeasonEditAction.STARTS_AT.value,
            }
        ),
        clear=AsyncMock(),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="2.09.2026",
        answer=AsyncMock(),
    )

    await admin_handlers.enter_season_edit_value(message, state)

    calendar_service.update_season_prompt.assert_awaited_once_with(
        prompt_id=7,
        starts_at=date(2026, 9, 2),
    )
    state.clear.assert_awaited_once()
    assert message.answer.await_args.args[0] == (
        "Будет создан новый сезон:\n"
        "Осень 2026\n"
        "Период: 2.09.2026 — 30.11.2026"
    )


async def test_season_edit_value_rejects_invalid_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    player_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(update_season_prompt=AsyncMock())
    monkeypatch.setattr(admin_handlers, "player_service", player_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                "season_prompt_id": 7,
                "season_edit_field": keyboards.SeasonEditAction.ENDS_AT.value,
            }
        ),
        clear=AsyncMock(),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="2026-11-30",
        answer=AsyncMock(),
    )

    await admin_handlers.enter_season_edit_value(message, state)

    calendar_service.update_season_prompt.assert_not_awaited()
    state.clear.assert_not_awaited()
    message.answer.assert_awaited_once_with("Дата должна быть в формате 1.09.2026.")


async def test_season_edit_value_rejects_invalid_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    player_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        update_season_prompt=AsyncMock(side_effect=CalendarPromptInvalidPayloadError)
    )
    monkeypatch.setattr(admin_handlers, "player_service", player_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                "season_prompt_id": 7,
                "season_edit_field": keyboards.SeasonEditAction.STARTS_AT.value,
            }
        ),
        clear=AsyncMock(),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="1.12.2026",
        answer=AsyncMock(),
    )

    await admin_handlers.enter_season_edit_value(message, state)

    calendar_service.update_season_prompt.assert_awaited_once_with(
        prompt_id=7,
        starts_at=date(2026, 12, 1),
    )
    state.clear.assert_not_awaited()
    message.answer.assert_awaited_once_with(
        "Дата начала не может быть позже даты окончания. "
        "Введи дату начала в формате 1.09.2026."
    )


async def test_admin_panel_registration_requests_button_shows_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(
            return_value=AdminPanelView(admin=admin, reviews=[])
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.show_pending_registrations(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once_with("Новых заявок нет.")


async def test_admin_panel_registration_requests_button_shows_paginated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    reviews = [registration_review(player_id) for player_id in range(10, 17)]
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(
            return_value=AdminPanelView(admin=admin, reviews=reviews)
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.show_pending_registrations(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == (
        "Заявки на регистрацию\n\n"
        "10 — Игрок 10\n"
        "11 — Игрок 11\n"
        "12 — Игрок 12\n"
        "13 — Игрок 13\n"
        "14 — Игрок 14\n"
        "15 — Игрок 15\n\n"
        "Страница 1/2"
    )
    buttons = [
        button.text
        for row in answer.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["10", "11", "12", "13", "14", "15", "➡️", "❌ Отмена"]


async def test_admin_registration_list_page_callback_edits_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    reviews = [registration_review(player_id) for player_id in range(10, 17)]
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(
            return_value=AdminPanelView(admin=admin, reviews=reviews)
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationListAction.PAGE,
        page=1,
        player_id=0,
    )

    await admin_handlers.review_registration_list(callback, callback_data)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == (
        "Заявки на регистрацию\n\n"
        "16 — Игрок 16\n\n"
        "Страница 2/2"
    )
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["16", "⬅️", "❌ Отмена"]


async def test_admin_registration_list_cancel_deletes_message() -> None:
    message = SimpleNamespace(delete=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationListAction.CANCEL,
        page=0,
        player_id=0,
    )

    await admin_handlers.review_registration_list(callback, callback_data)

    callback.answer.assert_awaited_once_with("Заявка скрыта")
    message.delete.assert_awaited_once()


async def test_admin_registration_list_open_edits_message_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = registration_review(10)
    service = SimpleNamespace(
        get_registration_review_for_admin=AsyncMock(return_value=review)
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationListAction.OPEN,
        page=0,
        player_id=10,
    )

    await admin_handlers.review_registration_list(callback, callback_data)

    service.get_registration_review_for_admin.assert_awaited_once_with(
        admin_telegram_id=100,
        pending_player_id=10,
    )
    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()
    assert "Новая заявка на регистрацию" in message.edit_text.await_args.args[0]
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["✅ Одобрить", "🚫 Отклонить", "❌ Отмена"]


async def test_admin_panel_exit_returns_main_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(
            return_value=AdminPanelView(admin=admin, reviews=[])
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.exit_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == "Главное меню."
    assert keyboards.MAIN_ADMIN in keyboard_texts(answer.kwargs["reply_markup"])


async def test_admin_panel_denies_regular_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(side_effect=AdminAccessDeniedError)
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once_with("У тебя нет доступа в админ-панель!")


async def test_registration_review_keyboard_with_history_has_action_labels() -> None:
    keyboard = keyboards.registration_review_keyboard(player_id=10, has_matches=True)

    buttons = [
        button.text
        for row in keyboard.inline_keyboard
        for button in row
    ]
    assert buttons == [
        "🔗 Связать с историей",
        "🆕 Сохранить нового пользователя",
        "🚫 Отклонить",
        "❌ Отмена",
    ]
    assert [len(row) for row in keyboard.inline_keyboard] == [1, 1, 1, 1]


async def test_registration_review_cancel_deletes_message_without_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_registration_matches_for_admin=AsyncMock(),
        approve_registration=AsyncMock(),
        reject_registration=AsyncMock(),
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(delete=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationReviewAction.CANCEL,
        player_id=10,
    )

    await admin_handlers.review_registration(callback, callback_data)

    callback.answer.assert_awaited_once_with("Заявка скрыта")
    message.delete.assert_awaited_once()
    service.get_registration_matches_for_admin.assert_not_awaited()
    service.approve_registration.assert_not_awaited()
    service.reject_registration.assert_not_awaited()


async def test_registration_review_reject_deletes_pending_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = PlayerView(
        id=10,
        telegram_id=200,
        display_name="Игрок Второй",
        full_name="Игрок Второй",
        nickname=None,
        status=PlayerStatusView.PENDING,
        role=PlayerRoleView.USER,
    )
    reviewer = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    other_admin = admin_player(2, 101)
    service = SimpleNamespace(
        reject_registration=AsyncMock(
            return_value=RegistrationReviewResultView(
                player=player,
                admins=[reviewer, other_admin],
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_text=AsyncMock(),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        bot=bot,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationReviewAction.REJECT,
        player_id=10,
    )

    await admin_handlers.review_registration(callback, callback_data)

    service.reject_registration.assert_awaited_once_with(
        admin_telegram_id=100,
        player_id=10,
    )
    message.edit_text.assert_awaited_once()
    assert callback.answer.await_args.args[0] == "Заявка отклонена"
    assert bot.send_message.await_count == 2
    admin_call, player_call = bot.send_message.await_args_list
    assert admin_call.kwargs["chat_id"] == 101
    assert "Заявка отклонена: Админ 1" in admin_call.kwargs["text"]
    assert player_call.kwargs["chat_id"] == 200


async def test_registration_review_with_multiple_matches_shows_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matches = [registration_match(20, 100), registration_match(21, 92)]
    service = SimpleNamespace(
        get_registration_matches_for_admin=AsyncMock(return_value=matches),
        approve_registration=AsyncMock(),
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_reply_markup=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationReviewAction.APPROVE,
        player_id=10,
    )

    await admin_handlers.review_registration(callback, callback_data)

    service.get_registration_matches_for_admin.assert_awaited_once_with(
        admin_telegram_id=100,
        pending_player_id=10,
    )
    service.approve_registration.assert_not_awaited()
    callback.answer.assert_awaited_once_with()
    message.edit_reply_markup.assert_awaited_once()
    selection_keyboard = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    buttons = [
        button.text
        for row in selection_keyboard.inline_keyboard
        for button in row
    ]
    assert buttons == [
        "1. Исторический 20 (100%)",
        "2. Исторический 21 (92%)",
        "🚫 Отклонить",
        "❌ Отмена",
    ]


async def test_selected_registration_match_is_approved_and_sent_to_other_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = PlayerView(
        id=21,
        telegram_id=200,
        display_name="Исторический 21",
        full_name="Исторический 21",
        nickname=None,
        status=PlayerStatusView.ACTIVE,
        role=PlayerRoleView.USER,
    )
    reviewer = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    other_admin = admin_player(2, 101)
    service = SimpleNamespace(
        approve_registration=AsyncMock(
            return_value=RegistrationReviewResultView(
                player=player,
                admins=[reviewer, other_admin],
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_text=AsyncMock(),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        bot=bot,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(player_id=10, historical_player_id=21)

    await admin_handlers.select_registration_match(callback, callback_data)

    service.approve_registration.assert_awaited_once_with(
        admin_telegram_id=100,
        player_id=10,
        historical_player_id=21,
    )
    message.edit_text.assert_awaited_once()
    assert callback.answer.await_args.args[0] == "Заявка одобрена"
    assert bot.send_message.await_count == 2
    admin_call, player_call = bot.send_message.await_args_list
    assert admin_call.kwargs["chat_id"] == 101
    assert "Заявка одобрена: Админ 1" in admin_call.kwargs["text"]
    assert player_call.kwargs["chat_id"] == 200


async def test_registration_review_result_is_sent_to_other_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = PlayerView(
        id=10,
        telegram_id=200,
        display_name="Игрок Второй",
        full_name="Игрок Второй",
        nickname=None,
        status=PlayerStatusView.ACTIVE,
        role=PlayerRoleView.ADMIN,
    )
    reviewer = admin_player(1, 100, PlayerRoleView.SUPERADMIN)
    other_admin = admin_player(2, 101)
    service = SimpleNamespace(
        get_registration_matches_for_admin=AsyncMock(return_value=[]),
        approve_registration=AsyncMock(
            return_value=RegistrationReviewResultView(
                player=player,
                admins=[reviewer, other_admin],
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "player_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_text=AsyncMock(),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        bot=bot,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationReviewAction.APPROVE,
        player_id=10,
    )

    await admin_handlers.review_registration(callback, callback_data)

    service.approve_registration.assert_awaited_once_with(
        admin_telegram_id=100,
        player_id=10,
        use_registration_match=True,
    )
    message.edit_text.assert_awaited_once()
    assert callback.answer.await_args.args[0] == "Заявка одобрена"
    assert bot.send_message.await_count == 2
    admin_call, player_call = bot.send_message.await_args_list
    assert admin_call.kwargs["chat_id"] == 101
    assert "Заявка одобрена: Админ 1" in admin_call.kwargs["text"]
    assert player_call.kwargs["chat_id"] == 200
    assert player_call.kwargs["text"] == "Игрок Второй, ты успешно зарегистрирован/а!"
    assert keyboards.MAIN_ADMIN not in keyboard_texts(player_call.kwargs["reply_markup"])


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
