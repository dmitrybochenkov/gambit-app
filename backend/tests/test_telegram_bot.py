from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import telegram_webhook as webhook_module
from app.bot.telegram import keyboards, notifications, runtime
from app.bot.telegram.formatters import (
    format_admin_result_close_confirmation,
    format_admin_result_menu,
    format_admin_result_players,
    format_season_proposal,
)
from app.bot.telegram.handlers import admin as admin_handlers
from app.bot.telegram.handlers import user as user_handlers
from app.db.base import Base
from app.db.factories import create_user
from app.db.models import User
from app.db.models.enums import UserRole
from app.services.calendar_service import CalendarTournamentDateAlreadyExistsError
from app.services.dto import (
    AdminPanelView,
    PointsRatingView,
    RatingResultView,
    RegistrationCandidateView,
    RegistrationNotificationView,
    RegistrationRequestView,
    RegistrationReviewResultView,
    RegistrationReviewView,
    ScoringConfigView,
    SeasonLifecycleStateView,
    SeasonProposalView,
    SeasonView,
    TournamentPromptDayEditView,
    TournamentPromptItemView,
    TournamentPromptView,
    TournamentRebuyView,
    TournamentResultDraftPlayerView,
    TournamentResultDraftView,
    TournamentTypeDetailView,
    TournamentTypeOptionView,
    TournamentView,
    UserRoleView,
    UserStartStatusView,
    UserStartView,
    UserStatusView,
    UserView,
)
from app.services.pagination import Page
from app.services.profile_service import ProfileKind
from app.services.rating_service import RatingKind
from app.services.user_service import AdminAccessDeniedError, UserService


def active_player() -> UserView:
    return UserView(
        id=1,
        telegram_id=123,
        display_name="Игрок Первый",
        status=UserStatusView.ACTIVE,
        role=UserRoleView.PLAYER,
    )


def scoring_config_view(config_id: int = 1) -> ScoringConfigView:
    return ScoringConfigView(
        id=config_id,
        place_1_coefficient=Decimal("0.45"),
        place_2_coefficient=Decimal("0.25"),
        place_3_coefficient=Decimal("0.15"),
        place_4_coefficient=Decimal("0.10"),
        place_5_coefficient=Decimal("0.05"),
        knockout_small_points=15,
        knockout_big_points=60,
    )


def season_view(season_id: int = 1) -> SeasonView:
    return SeasonView(
        id=season_id,
        name="Осень 2026",
        starts_at=date(2026, 9, 1),
        ends_at=None,
        lifecycle_state=SeasonLifecycleStateView.CURRENT,
        scoring_config_id=1,
    )


def season_proposal_view(proposal_id: int = 9) -> SeasonProposalView:
    return SeasonProposalView(
        id=proposal_id,
        name="Лето 2026",
        starts_at=date(2026, 7, 28),
        scoring_config_id=1,
    )


def tournament_type_detail_view(
    *,
    type_id: int = 1,
    name: str = "Баунти турнир",
    entry_fee: int = 600,
    entry_stack: int = 20_000,
    addon_fee: int = 800,
    addon_stack: int = 125_000,
    rebuys: list[TournamentRebuyView] | None = None,
    knockout_mode: str = "none",
) -> TournamentTypeDetailView:
    return TournamentTypeDetailView(
        id=type_id,
        name=name,
        description=None,
        entry_fee=entry_fee,
        entry_stack=entry_stack,
        addon_fee=addon_fee,
        addon_stack=addon_stack,
        rebuys=rebuys or [TournamentRebuyView(fee=600, stack=30_000)],
        knockout_mode=knockout_mode,
    )


def tournament_prompt_view(
    *,
    prompt_id: int = 8,
    tournament_type: TournamentTypeDetailView | None = None,
    tournaments: list[TournamentPromptItemView] | None = None,
) -> TournamentPromptView:
    return TournamentPromptView(
        id=prompt_id,
        kind="tournaments_proposal",
        status="pending",
        tournaments=tournaments
        or [
            TournamentPromptItemView(
                date=date(2026, 7, 22),
                tournament_type=tournament_type or tournament_type_detail_view(),
            ),
            TournamentPromptItemView(
                date=date(2026, 7, 23),
                tournament_type=tournament_type_detail_view(
                    type_id=2,
                    name="Классика",
                ),
            ),
            TournamentPromptItemView(
                date=date(2026, 7, 24),
                tournament_type=tournament_type_detail_view(
                    type_id=3,
                    name="Фризаут",
                    entry_fee=1000,
                    entry_stack=50_000,
                    addon_fee=1000,
                    addon_stack=175_000,
                    rebuys=[TournamentRebuyView(fee=1000, stack=75_000)],
                ),
            ),
            TournamentPromptItemView(
                date=date(2026, 7, 25),
                tournament_type=tournament_type_detail_view(
                    type_id=4,
                    name="Double Double",
                ),
            ),
            TournamentPromptItemView(
                date=date(2026, 7, 26),
                tournament_type=tournament_type_detail_view(
                    type_id=5,
                    name="Mystery Bounty",
                    knockout_mode="mystery",
                ),
            ),
        ],
    )


def test_parse_result_manual_value() -> None:
    assert (
        admin_handlers.parse_result_manual_value(
            "17",
            field=keyboards.AdminResultField.KNOCKOUTS,
        )
        == 17
    )
    assert (
        admin_handlers.parse_result_manual_value(
            "10",
            field=keyboards.AdminResultField.BIG_KNOCKOUTS,
        )
        == 10
    )
    assert (
        admin_handlers.parse_result_manual_value(
            "5",
            field=keyboards.AdminResultField.PLACE,
        )
        == 5
    )


def test_parse_result_manual_value_rejects_place_outside_top_five() -> None:
    with pytest.raises(ValueError):
        admin_handlers.parse_result_manual_value(
            "6",
            field=keyboards.AdminResultField.PLACE,
        )


def test_admin_result_players_hide_ids_and_empty_places() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    players = [
        TournamentResultDraftPlayerView(
            player_id=252,
            display_name="Тест Игрок",
            place=None,
            knockouts_count=0,
            big_knockouts_count=0,
        ),
        TournamentResultDraftPlayerView(
            player_id=108,
            display_name="Илларионов Александр",
            place=2,
            knockouts_count=0,
            big_knockouts_count=0,
        ),
    ]
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("1800"),
        players=players,
        knockout_mode="none",
    )
    page = Page(items=players, page=0, page_size=6, total_items=2)

    assert format_admin_result_players(draft, page) == (
        "Игроки турнира\n"
        "Воскресенье, 19 июля — Классика\n\n"
        "```\n"
        "| Место | Игрок\n"
        "| ----- | -----\n"
        "|     1 | НЕ ВВЕДЕНО\n"
        "|     2 | Илларионов Александр\n"
        "|     3 | НЕ ВВЕДЕНО\n"
        "|     4 | НЕ ВВЕДЕНО\n"
        "|     5 | НЕ ВВЕДЕНО\n"
        "```"
    )
    buttons = [
        button.text
        for row in keyboards.admin_result_players_keyboard(draft, page).inline_keyboard
        for button in row
    ]
    assert buttons == [
        "Тест Игрок",
        "Илларионов Александр: 2️⃣",
        "⬅️ Назад",
        "❌ Отмена",
    ]


def test_admin_result_players_show_empty_state_without_entered_results() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    players = [
        TournamentResultDraftPlayerView(
            player_id=252,
            display_name="Тест Игрок",
            place=None,
            knockouts_count=0,
            big_knockouts_count=0,
        )
    ]
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("1800"),
        players=players,
        knockout_mode="none",
    )
    page = Page(items=players, page=0, page_size=6, total_items=1)

    assert format_admin_result_players(draft, page) == (
        "Игроки турнира\n"
        "Воскресенье, 19 июля — Классика\n\n"
        "```\n"
        "| Место | Игрок\n"
        "| ----- | -----\n"
        "|     1 | НЕ ВВЕДЕНО\n"
        "|     2 | НЕ ВВЕДЕНО\n"
        "|     3 | НЕ ВВЕДЕНО\n"
        "|     4 | НЕ ВВЕДЕНО\n"
        "|     5 | НЕ ВВЕДЕНО\n"
        "```"
    )


def test_admin_result_player_buttons_show_entered_knockouts_and_place() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    players = [
        TournamentResultDraftPlayerView(
            player_id=108,
            display_name="Илларионов Александр",
            place=2,
            knockouts_count=3,
            big_knockouts_count=1,
        ),
        TournamentResultDraftPlayerView(
            player_id=252,
            display_name="Тест Игрок",
            place=None,
            knockouts_count=0,
            big_knockouts_count=0,
        ),
    ]
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("1800"),
        players=players,
        knockout_mode="small_big",
    )
    page = Page(items=players, page=0, page_size=6, total_items=2)

    buttons = [
        button.text
        for row in keyboards.admin_result_players_keyboard(draft, page).inline_keyboard
        for button in row
    ]

    assert buttons == [
        "Илларионов Александр: 2️⃣ | 💥🥊 х1 | 🥊 х3",
        "Тест Игрок",
        "⬅️ Назад",
        "❌ Отмена",
    ]


def test_admin_result_menu_shows_entered_results_under_pool() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("2200"),
        players=[
            TournamentResultDraftPlayerView(
                player_id=255,
                display_name="Тест Игрок 4",
                place=2,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultDraftPlayerView(
                player_id=1,
                display_name="Дима Боченков",
                place=4,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultDraftPlayerView(
                player_id=252,
                display_name="Тест Игрок 1",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultDraftPlayerView(
                player_id=258,
                display_name="Тест Игрок 7",
                place=5,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultDraftPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
        ],
        knockout_mode="none",
    )

    assert format_admin_result_menu(draft) == (
        "Внесение результатов\n"
        "Воскресенье, 19 июля — Классика\n"
        "Пул: 2200\n"
        "```\n"
        "| Место | Игрок\n"
        "| ----- | -----\n"
        "|     1 | Тест Игрок 1\n"
        "|     2 | Тест Игрок 4\n"
        "|     3 | НЕ ВВЕДЕНО\n"
        "|     4 | Дима Боченков\n"
        "|     5 | Тест Игрок 7\n"
        "```\n\n"
        "Игроков: 5"
    )


def test_admin_result_menu_sorts_without_places_by_big_and_small_knockouts() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("2200"),
        players=[
            TournamentResultDraftPlayerView(
                player_id=1,
                display_name="Игрок КО",
                place=None,
                knockouts_count=4,
                big_knockouts_count=1,
            ),
            TournamentResultDraftPlayerView(
                player_id=2,
                display_name="Игрок БКО",
                place=None,
                knockouts_count=1,
                big_knockouts_count=2,
            ),
            TournamentResultDraftPlayerView(
                player_id=3,
                display_name="Игрок Место",
                place=3,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultDraftPlayerView(
                player_id=4,
                display_name="Игрок Много КО",
                place=None,
                knockouts_count=7,
                big_knockouts_count=1,
            ),
        ],
        knockout_mode="small_big",
    )

    assert format_admin_result_menu(draft) == (
        "Внесение результатов\n"
        "Воскресенье, 19 июля — Boss Bounty\n"
        "Пул: 2200\n"
        "```\n"
        "| Место | Игрок\n"
        "| ----- | -----\n"
        "|     1 | НЕ ВВЕДЕНО\n"
        "|     2 | НЕ ВВЕДЕНО\n"
        "|     3 | Игрок Место\n"
        "|     4 | НЕ ВВЕДЕНО\n"
        "|     5 | НЕ ВВЕДЕНО\n"
        "```\n\n"
        "🥊:\n"
        "Игрок БКО: 💥🥊 х2, 🥊 х1\n"
        "Игрок Много КО: 💥🥊 х1, 🥊 х7\n"
        "Игрок КО: 💥🥊 х1, 🥊 х4\n\n"
        "Игроков: 4"
    )


def test_admin_result_menu_shows_empty_results_state() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("2200"),
        players=[
            TournamentResultDraftPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            )
        ],
        knockout_mode="none",
    )

    assert format_admin_result_menu(draft) == (
        "Внесение результатов\n"
        "Воскресенье, 19 июля — Классика\n"
        "Пул: 2200\n"
        "```\n"
        "| Место | Игрок\n"
        "| ----- | -----\n"
        "|     1 | НЕ ВВЕДЕНО\n"
        "|     2 | НЕ ВВЕДЕНО\n"
        "|     3 | НЕ ВВЕДЕНО\n"
        "|     4 | НЕ ВВЕДЕНО\n"
        "|     5 | НЕ ВВЕДЕНО\n"
        "```\n\n"
        "Игроков: 1"
    )


def test_admin_result_menu_has_close_without_check() -> None:
    buttons = [
        button.text
        for row in keyboards.admin_result_menu_keyboard(125).inline_keyboard
        for button in row
    ]

    assert buttons == [
        "💰 Пул",
        "👥 Игроки",
        "✅ Закрыть турнир",
        "❌ Отмена",
    ]


def test_admin_result_close_confirmation_shows_pool_and_results() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("1800"),
        players=[
            TournamentResultDraftPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=2,
                knockouts_count=3,
                big_knockouts_count=1,
            ),
            TournamentResultDraftPlayerView(
                player_id=252,
                display_name="Тест Игрок",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
        ],
        knockout_mode="small_big",
    )

    assert format_admin_result_close_confirmation(draft) == (
        "Подтверди закрытие турнира\n"
        "Воскресенье, 19 июля — Boss Bounty\n"
        "Пул: 1800\n\n"
        "Результаты:\n"
        "• Илларионов Александр: 2️⃣ | 💥🥊 х1 | 🥊 х3\n"
        "• Тест Игрок"
    )


def test_admin_result_player_field_and_value_keyboards() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    player = TournamentResultDraftPlayerView(
        player_id=108,
        display_name="Илларионов Александр",
        place=None,
        knockouts_count=0,
        big_knockouts_count=0,
    )
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("1800"),
        players=[player],
        knockout_mode="small_big",
    )

    field_buttons = [
        button.text
        for row in keyboards.admin_result_player_fields_keyboard(
            draft,
            player,
            page=0,
        ).inline_keyboard
        for button in row
    ]
    assert field_buttons == [
        "🥊 КО",
        "💥🥊 Большие КО",
        "🏁 Место",
        "✅ Готово",
        "❌ Отмена",
    ]

    value_rows = keyboards.admin_result_value_keyboard(
        tournament_id=125,
        page=0,
        player_id=108,
        field=keyboards.AdminResultField.KNOCKOUTS,
    ).inline_keyboard
    assert [[button.text for button in row] for row in value_rows] == [
        ["1", "2", "3", "4", "5"],
        ["6", "7", "8", "9", "10"],
        ["11", "12", "13", "14", "15"],
        ["⌨️ Ввести руками"],
        ["⬅️ Назад"],
        ["❌ Отмена"],
    ]

    place_rows = keyboards.admin_result_value_keyboard(
        tournament_id=125,
        page=0,
        player_id=108,
        field=keyboards.AdminResultField.PLACE,
        occupied_places={2, 5},
    ).inline_keyboard
    assert [[button.text for button in row] for row in place_rows] == [
        ["1", "✔️ 2", "3", "4", "✔️ 5"],
        ["⬅️ Назад"],
        ["❌ Отмена"],
    ]


async def test_place_only_result_player_opens_place_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    target_player = TournamentResultDraftPlayerView(
        player_id=108,
        display_name="Илларионов Александр",
        place=None,
        knockouts_count=0,
        big_knockouts_count=0,
    )
    draft = TournamentResultDraftView(
        tournament=tournament,
        points_pool=Decimal("1800"),
        players=[
            target_player,
            TournamentResultDraftPlayerView(
                player_id=252,
                display_name="Тест Игрок",
                place=2,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
        ],
        knockout_mode="none",
    )
    service = SimpleNamespace(get_or_create_draft=AsyncMock(return_value=draft))
    monkeypatch.setattr(admin_handlers, "result_service", service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.select_result_player(
        callback,
        keyboards.AdminResultPlayerCallback(
            action=keyboards.AdminResultPlayerAction.OPEN,
            tournament_id=125,
            page=0,
            player_id=108,
        ),
        state,
    )

    state.clear.assert_awaited_once()
    callback.answer.assert_awaited_once()
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == ("Илларионов Александр\n\nВыбери место:")
    assert [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ] == ["1", "✔️ 2", "3", "4", "5", "⬅️ Назад", "❌ Отмена"]


def admin_player(
    player_id: int,
    telegram_id: int,
    role: UserRoleView = UserRoleView.ADMIN,
) -> UserView:
    return UserView(
        id=player_id,
        telegram_id=telegram_id,
        display_name=f"Админ {player_id}",
        status=UserStatusView.ACTIVE,
        role=role,
    )


def tournament_view(
    tournament_id: int,
    tournament_date: date,
    tournament_type_id: int,
    tournament_type_name: str | None = None,
) -> TournamentView:
    return TournamentView(
        id=tournament_id,
        date=tournament_date,
        tournament_type_id=tournament_type_id,
        tournament_type_name=tournament_type_name,
    )


def keyboard_texts(reply_markup: object) -> list[str]:
    return [button.text for row in reply_markup.keyboard for button in row]


def registration_match(player_id: int, score: int) -> RegistrationCandidateView:
    return RegistrationCandidateView(
        user=UserView(
            id=player_id,
            telegram_id=None,
            display_name=f"Исторический {player_id}",
            status=UserStatusView.ACTIVE,
            role=UserRoleView.PLAYER,
        ),
        score=score,
        reason=f"имя похоже на {score}%",
    )


def registration_review(player_id: int) -> RegistrationReviewView:
    return RegistrationReviewView(
        request=RegistrationRequestView(
            id=player_id,
            telegram_id=1000 + player_id,
            request_type="new_player",
            status="pending",
            requested_display_name=f"Игрок {player_id}",
            requested_link_name=None,
            candidate_user_id=None,
            created_at="27.07.2026 12:00",
        ),
        candidates=[],
    )


async def test_start_command_opens_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock(), update_data=AsyncMock())
    service = SimpleNamespace(
        get_start_view=AsyncMock(
            return_value=UserStartView(status=UserStartStatusView.NEEDS_REGISTRATION)
        ),
    )
    monkeypatch.setattr(user_handlers, "user_service", service)

    await user_handlers.start_command(message, state)

    state.clear.assert_awaited_once()
    service.get_start_view.assert_awaited_once_with(123)
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == user_handlers.texts.user.REGISTRATION_GREETING
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == ["🆕 Нет, я новый игрок", "🔗 Да, играл ранее"]


async def test_start_command_shows_admin_keyboard_for_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())
    service = SimpleNamespace(
        get_start_view=AsyncMock(
            return_value=UserStartView(
                status=UserStartStatusView.REGISTERED,
                user=admin_player(1, 123),
            )
        )
    )
    monkeypatch.setattr(user_handlers, "user_service", service)

    await user_handlers.start_command(message, state)

    state.clear.assert_awaited_once()
    service.get_start_view.assert_awaited_once_with(123)
    assert message.answer.await_count == 1
    reply_markup = message.answer.await_args.kwargs["reply_markup"]
    assert keyboards.MAIN_ADMIN in keyboard_texts(reply_markup)


async def test_start_command_is_idempotent_for_imported_historical_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'start_user.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        user = create_user(
            telegram_id=123,
            display_name="Дима Боченков",
            role=UserRole.SUPERADMIN,
        )
        user.id = 1
        session.add(user)
        await session.commit()

    monkeypatch.setattr(user_handlers, "user_service", UserService(session_factory))
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )

    try:
        await user_handlers.start_command(message, state)
        await user_handlers.start_command(message, state)

        async with session_factory() as session:
            users = list((await session.execute(select(User))).scalars())

        assert len(users) == 1
        assert users[0].id == 1
        assert users[0].telegram_id == 123
        assert users[0].display_name == "Дима Боченков"
        assert message.answer.await_count == 2
    finally:
        await engine.dispose()


async def test_historical_admin_can_open_schedule_after_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = admin_player(1, 123, role=UserRoleView.SUPERADMIN)
    user_service = SimpleNamespace(
        get_start_view=AsyncMock(
            return_value=UserStartView(
                status=UserStartStatusView.REGISTERED,
                user=user,
            )
        )
    )
    tournament = tournament_view(7, date(2026, 7, 8), 1, "Баунти турнир")
    tournament_service = SimpleNamespace(
        get_schedule_for_player=AsyncMock(return_value=[tournament])
    )
    monkeypatch.setattr(user_handlers, "user_service", user_service)
    monkeypatch.setattr(user_handlers, "tournament_service", tournament_service)
    state = SimpleNamespace(clear=AsyncMock())
    start_message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    schedule_message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )

    await user_handlers.start_command(start_message, state)
    await user_handlers.show_tournament_schedule(schedule_message)

    user_service.get_start_view.assert_awaited_once_with(123)
    tournament_service.get_schedule_for_player.assert_awaited_once_with(123)
    assert start_message.answer.await_args.args[0] == "Админ 1, добро пожаловать!"
    assert schedule_message.answer.await_args.args[0] == (
        "Расписание турниров\n\n• Среда, 8 июля — Баунти турнир"
    )


async def test_schedule_still_requires_registered_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament_service = SimpleNamespace(
        get_schedule_for_player=AsyncMock(
            side_effect=user_handlers.TournamentScheduleNotAllowedError
        )
    )
    monkeypatch.setattr(user_handlers, "tournament_service", tournament_service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=404),
        answer=AsyncMock(),
    )

    await user_handlers.show_tournament_schedule(message)

    tournament_service.get_schedule_for_player.assert_awaited_once_with(404)
    message.answer.assert_awaited_once_with(user_handlers.texts.user.SCHEDULE_UNAVAILABLE)


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
    service = SimpleNamespace(require_active_user=AsyncMock(return_value=active_player()))
    monkeypatch.setattr(user_handlers, "user_service", service)

    await user_handlers.show_club_address(message)

    service.require_active_user.assert_awaited_once_with(123)
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
    service = SimpleNamespace(require_active_user=AsyncMock(return_value=active_player()))
    monkeypatch.setattr(user_handlers, "user_service", service)

    await user_handlers.show_rating_menu(message)

    answer = message.answer.await_args
    assert answer.args[0] == "Какой рейтинг ты хочешь посмотреть?"
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == [
        "🏆 Текущий сезон",
        "🏆⏳ За все время",
        "🥊 Нокауты",
        "🥊⏳ Нокауты за все время",
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
        "Рейтинг — текущий сезон\n"
        "🎲 - количество турниров\n\n"
        "🥇 ✅ *Игрок Первый* — 120 | 🎲 3"
    )
    assert message.edit_text.await_args.kwargs["parse_mode"] == "Markdown"
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["1-1 из 1", "❌ Закрыть рейтинг"]


async def test_rating_callback_opens_current_player_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        PointsRatingView(
            player_id=player_id,
            display_name=f"Игрок {player_id}",
            total_points=Decimal(100 - player_id),
            tournaments_count=1,
        )
        for player_id in range(1, 13)
    ]
    rating_service = SimpleNamespace(
        get_rating_for_player=AsyncMock(
            return_value=RatingResultView(
                title="Рейтинг — текущий сезон",
                rows=rows,
                current_player_id=12,
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
    callback_data = SimpleNamespace(kind=RatingKind.CURRENT_SEASON, page=-1)

    await user_handlers.show_rating(callback, callback_data)

    assert "11. Игрок 11" in message.edit_text.await_args.args[0]
    assert "*Игрок 12*" in message.edit_text.await_args.args[0]
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["⬅️", "11-12 из 12", "❌ Закрыть рейтинг"]


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
    service = SimpleNamespace(require_active_user=AsyncMock(return_value=active_player()))
    monkeypatch.setattr(user_handlers, "user_service", service)

    await user_handlers.show_profile_menu(message)

    answer = message.answer.await_args
    assert answer.args[0] == "За какой период ты хочешь посмотреть свои достижения?"
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == ["🏆 За текущий сезон", "⏳ За все время", "❌ Отмена"]


async def test_profile_callback_sends_selected_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_service = SimpleNamespace(
        get_profile_for_player=AsyncMock(return_value=("Твой профиль — текущий сезон", None))
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
        get_registration_options_for_player=AsyncMock(return_value=[tournament]),
        get_player_upcoming_registrations=AsyncMock(return_value=[]),
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


async def test_registration_button_marks_existing_registrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    tournaments = [
        tournament_view(7, date(2026, 7, 8), 1, "Баунти турнир"),
        tournament_view(8, date(2026, 7, 9), 2, "Классика"),
    ]
    tournament_service = SimpleNamespace(
        get_registration_options_for_player=AsyncMock(return_value=tournaments),
        get_player_upcoming_registrations=AsyncMock(return_value=[tournaments[1]]),
    )
    state = SimpleNamespace(update_data=AsyncMock())
    monkeypatch.setattr(user_handlers, "tournament_service", tournament_service)

    await user_handlers.show_tournaments_for_registration(message, state)

    rows = message.answer.await_args.kwargs["reply_markup"].inline_keyboard
    assert rows[0][0].text == "Среда, 8 июля — Баунти турнир"
    assert rows[1][0].text == "✔️ Четверг, 9 июля — Классика"
    state.update_data.assert_awaited_once_with(tournament_registration_selection=[8])


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
        get_registration_options_for_player=AsyncMock(return_value=tournaments),
        get_player_upcoming_registrations=AsyncMock(return_value=[]),
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
        tournament_view(7, date(2026, 7, 8), 1, "Баунти турнир"),
        tournament_view(8, date(2026, 7, 9), 2, "Классика"),
    ]
    service = SimpleNamespace(register_player_for_tournaments=AsyncMock(return_value=tournaments))
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
        get_data=AsyncMock(return_value={"tournament_registration_selection": [7, 8]}),
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
    assert "Среда, 8 июля — Баунти турнир" in confirmation
    assert "Четверг, 9 июля — Классика" in confirmation
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
    service = SimpleNamespace(get_player_upcoming_registrations=AsyncMock(return_value=[]))
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
        tournament_view(7, date(2026, 7, 8), 1, "Баунти турнир"),
        tournament_view(8, date(2026, 7, 9), 2, "Классика"),
    ]
    service = SimpleNamespace(
        cancel_player_tournament_registrations=AsyncMock(return_value=tournaments)
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
        get_data=AsyncMock(return_value={"tournament_cancellation_selection": [7, 8]}),
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
    assert "Среда, 8 июля — Баунти турнир" in confirmation
    assert "Четверг, 9 июля — Классика" in confirmation


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
    request = RegistrationRequestView(
        id=10,
        telegram_id=200,
        request_type="new_player",
        status="pending",
        requested_display_name="Игрок Второй",
        requested_link_name=None,
        candidate_user_id=None,
        created_at="27.07.2026 12:00",
    )
    admins = [
        UserView(
            id=1,
            telegram_id=100,
            display_name="Админ Первый",
            status=UserStatusView.ACTIVE,
            role=UserRoleView.SUPERADMIN,
        ),
        UserView(
            id=2,
            telegram_id=101,
            display_name="Админ Второй",
            status=UserStatusView.ACTIVE,
            role=UserRoleView.ADMIN,
        ),
    ]
    service = SimpleNamespace(
        get_registration_notification=AsyncMock(
            return_value=RegistrationNotificationView(
                request=request,
                admins=admins,
                candidates=[],
            )
        ),
    )
    monkeypatch.setattr(notifications, "user_service", service)

    await notifications.notify_admins_about_registration(bot, request.id)

    service.get_registration_notification.assert_awaited_once_with(10)
    assert bot.send_message.await_count == 2
    assert bot.send_message.await_args_list[0].kwargs["chat_id"] == 100
    assert bot.send_message.await_args_list[1].kwargs["chat_id"] == 101
    assert "Telegram ID" not in bot.send_message.await_args_list[0].kwargs["text"]


async def test_admin_panel_entry_sends_admin_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[]))
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
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
        "📝 Зарегать игрока на турнир",
        "🏁 Внести результат",
        "👑 Суперадмин",
        "⬅️ Выход",
    ]


async def test_admin_panel_entry_shows_superadmin_button_for_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.ADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[]))
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_admin_panel(message)

    assert keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == [
        "📝 Зарегать игрока на турнир",
        "🏁 Внести результат",
        "👑 Суперадмин",
        "⬅️ Выход",
    ]


async def test_superadmin_panel_denies_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(require_superadmin=AsyncMock(side_effect=AdminAccessDeniedError))
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_superadmin_panel(message)

    service.require_superadmin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once_with("Недостаточно прав.")


async def test_superadmin_panel_button_opens_superadmin_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_superadmin_panel(message)

    service.require_superadmin.assert_awaited_once_with(100)
    assert message.answer.await_args.args[0] == "Суперадмин."
    assert keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == [
        "📝 Заявки на регистрацию",
        "🗓 Календарь",
        "➕ Добавить админа",
        "⬅️ Назад",
    ]


async def test_superadmin_panel_back_returns_admin_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[]))
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.back_to_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    assert message.answer.await_args.args[0] == "Добро пожаловать в админ-панель."
    assert keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == [
        "📝 Зарегать игрока на турнир",
        "🏁 Внести результат",
        "👑 Суперадмин",
        "⬅️ Выход",
    ]


async def test_admin_calendar_button_shows_inline_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_admin_calendar(message)

    service.require_superadmin.assert_awaited_once_with(100)
    answer = message.answer.await_args
    assert answer.args[0] == "Меню для создания сезонов и турниров в базе данных."
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == ["⏳ Сезоны", "🏆 Турниры", "❌ Отмена"]
    assert [len(row) for row in answer.kwargs["reply_markup"].inline_keyboard] == [
        1,
        1,
        1,
    ]


async def test_add_admin_button_shows_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = active_player()
    service = SimpleNamespace(
        list_admin_candidates_for_superadmin=AsyncMock(return_value=[candidate])
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.show_admin_candidates(message)

    service.list_admin_candidates_for_superadmin.assert_awaited_once_with(100)
    answer = message.answer.await_args
    assert answer.args[0] == "Кого назначаем админом?\n\n1 — Игрок Первый"
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == ["1. Игрок Первый", "❌ Отмена"]


async def test_admin_registration_button_shows_tournaments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    service = SimpleNamespace(
        list_registration_tournaments_for_admin=AsyncMock(return_value=[tournament])
    )
    monkeypatch.setattr(admin_handlers, "tournament_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.show_admin_registration_tournaments(message)

    service.list_registration_tournaments_for_admin.assert_awaited_once_with(100)
    answer = message.answer.await_args
    assert answer.args[0] == (
        "Выбери турнир для регистрации игрока:\n\n125 — Воскресенье, 19 июля — Классика"
    )
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == ["125", "❌ Отмена"]


async def test_admin_registration_tournament_selection_shows_players(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    player = active_player()
    service = SimpleNamespace(
        list_registration_tournaments_for_admin=AsyncMock(return_value=[tournament]),
        list_players_for_admin_registration=AsyncMock(return_value=[player]),
    )
    monkeypatch.setattr(admin_handlers, "tournament_service", service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )
    callback_data = SimpleNamespace(
        action=keyboards.AdminTournamentRegistrationTournamentAction.OPEN,
        page=0,
        tournament_id=125,
    )

    await admin_handlers.select_admin_registration_tournament(callback, callback_data)

    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == (
        "Кого регистрируем?\nВоскресенье, 19 июля — Классика\n\n1 — Игрок Первый"
    )
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == ["🔎 Найти игрока", "1. Игрок Первый", "⬅️ Назад", "❌ Отмена"]


async def test_admin_registration_player_selection_registers_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    player = active_player()
    service = SimpleNamespace(
        list_registration_tournaments_for_admin=AsyncMock(return_value=[tournament]),
        list_players_for_admin_registration=AsyncMock(return_value=[player]),
        register_player_for_tournament_by_admin=AsyncMock(return_value=(tournament, player)),
    )
    monkeypatch.setattr(admin_handlers, "tournament_service", service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )
    callback_data = SimpleNamespace(
        action=keyboards.AdminTournamentRegistrationPlayerAction.OPEN,
        tournament_id=125,
        page=0,
        player_id=1,
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.select_admin_registration_player(callback, callback_data, state)

    service.register_player_for_tournament_by_admin.assert_awaited_once_with(
        admin_telegram_id=100,
        tournament_id=125,
        player_id=1,
    )
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0] == (
        "Игрок зарегистрирован на турнир:\nИгрок Первый\nВоскресенье, 19 июля — Классика"
    )
    callback.bot.send_message.assert_awaited_once()
    assert callback.bot.send_message.await_args.kwargs["chat_id"] == 123
    assert callback.bot.send_message.await_args.kwargs["text"] == (
        "Ты зарегистрирован на турнир:\nВоскресенье, 19 июля — Классика"
    )
    state.clear.assert_awaited_once_with()


async def test_admin_registration_search_prompts_for_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    service = SimpleNamespace(
        list_registration_tournaments_for_admin=AsyncMock(return_value=[tournament]),
        list_players_for_admin_registration=AsyncMock(return_value=[active_player()]),
    )
    monkeypatch.setattr(admin_handlers, "tournament_service", service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.AdminTournamentRegistrationPlayerAction.SEARCH,
        tournament_id=125,
        page=0,
        player_id=0,
    )
    state = SimpleNamespace(set_state=AsyncMock(), update_data=AsyncMock())

    await admin_handlers.select_admin_registration_player(callback, callback_data, state)

    state.set_state.assert_awaited_once()
    state.update_data.assert_awaited_once_with(admin_registration_tournament_id=125)
    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == "Введи имя игрока."
    assert [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ] == ["❌ Отмена"]


async def test_admin_registration_search_shows_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    player = active_player()
    service = SimpleNamespace(
        list_registration_tournaments_for_admin=AsyncMock(return_value=[tournament]),
        search_players_for_admin_registration=AsyncMock(return_value=[player]),
    )
    monkeypatch.setattr(admin_handlers, "tournament_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="игрок",
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"admin_registration_tournament_id": 125}),
        clear=AsyncMock(),
    )

    await admin_handlers.enter_admin_registration_player_search(message, state)

    service.search_players_for_admin_registration.assert_awaited_once_with(
        admin_telegram_id=100,
        query="игрок",
    )
    state.clear.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == (
        "Нашел похожих игроков:\nВоскресенье, 19 июля — Классика\n\n1 — Игрок Первый"
    )
    assert [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ] == ["🔎 Искать заново", "1. Игрок Первый", "⬅️ Назад", "❌ Отмена"]


async def test_add_admin_button_denies_regular_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        list_admin_candidates_for_superadmin=AsyncMock(side_effect=AdminAccessDeniedError)
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.show_admin_candidates(message)

    message.answer.assert_awaited_once_with("Недостаточно прав.")


async def test_confirm_add_admin_promotes_player_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    promoted = admin_player(2, 200, UserRoleView.ADMIN)
    service = SimpleNamespace(add_admin=AsyncMock(return_value=promoted))
    monkeypatch.setattr(admin_handlers, "user_service", service)
    bot = SimpleNamespace(send_message=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
        bot=bot,
    )
    callback_data = SimpleNamespace(
        action=keyboards.AdminAddAction.CONFIRM,
        player_id=2,
    )

    await admin_handlers.confirm_add_admin(callback, callback_data)

    service.add_admin.assert_awaited_once_with(
        superadmin_telegram_id=100,
        player_id=2,
    )
    callback.answer.assert_awaited_once_with("Админ добавлен.")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with("Админ добавлен.")
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 200
    assert bot.send_message.await_args.kwargs["text"] == "Тебе назначена роль админа."
    assert "🛠 Админ-панель" in keyboard_texts(bot.send_message.await_args.kwargs["reply_markup"])


async def test_admin_calendar_seasons_callback_shows_generated_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    season_service = SimpleNamespace(
        create_season_proposal=AsyncMock(return_value=season_proposal_view())
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(action=keyboards.AdminCalendarAction.SEASONS)
    state = SimpleNamespace(set_state=AsyncMock(), update_data=AsyncMock(), clear=AsyncMock())

    await admin_handlers.select_admin_calendar_section(callback, callback_data, state)

    user_service.require_superadmin.assert_awaited_once_with(100)
    season_service.create_season_proposal.assert_awaited_once_with(100)
    state.set_state.assert_not_awaited()
    state.update_data.assert_not_awaited()
    state.clear.assert_awaited_once()
    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == ("🏆 Новый сезон\n\nНазвание: Лето 2026\nДата начала: 28 июля 2026")
    assert [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ] == ["✅ Создать", "✏️ Изменить", "❌ Отмена"]


def test_season_proposal_preview_shows_active_season_transition_from_dto() -> None:
    proposal = SeasonProposalView(
        id=9,
        name="Осень 2026",
        starts_at=date(2026, 8, 10),
        scoring_config_id=1,
        active_season_ends_at=date(2026, 8, 9),
    )

    assert format_season_proposal(proposal) == (
        "🏆 Новый сезон\n\n"
        "Название: Осень 2026\n"
        "Дата начала: 10 августа 2026\n\n"
        "Текущий сезон завершится: 9.08.2026\n"
        "Новый сезон начнётся: 10.08.2026\n\n"
        "Текущий активный сезон завершится за день до начала нового."
    )


async def test_admin_calendar_seasons_callback_handles_missing_scoring_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    season_service = SimpleNamespace(
        create_season_proposal=AsyncMock(
            side_effect=admin_handlers.SeasonScoringConfigNotFoundError
        )
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(set_state=AsyncMock(), update_data=AsyncMock(), clear=AsyncMock())

    await admin_handlers.select_admin_calendar_section(
        callback,
        SimpleNamespace(action=keyboards.AdminCalendarAction.SEASONS),
        state,
    )

    season_service.create_season_proposal.assert_awaited_once_with(100)
    state.set_state.assert_not_awaited()
    callback.answer.assert_awaited_once_with("Нет конфигураций начисления рейтинга.")
    message.answer.assert_awaited_once_with("Нет конфигураций начисления рейтинга.")


async def test_admin_calendar_tournaments_callback_shows_weekly_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        create_weekly_tournament_prompt=AsyncMock(return_value=tournament_prompt_view())
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(action=keyboards.AdminCalendarAction.TOURNAMENTS)
    state = SimpleNamespace(set_state=AsyncMock(), clear=AsyncMock())

    await admin_handlers.select_admin_calendar_section(callback, callback_data, state)

    calendar_service.create_weekly_tournament_prompt.assert_awaited_once_with()
    state.set_state.assert_not_awaited()
    state.clear.assert_awaited_once()
    callback.answer.assert_awaited_once_with()
    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0].startswith("Будет создано расписание:\n\n")
    assert answer.args[0] == (
        "Будет создано расписание:\n\n"
        "Среда, 22 июля — Баунти турнир\n"
        "Четверг, 23 июля — Классика\n"
        "Пятница, 24 июля — Фризаут\n"
        "Суббота, 25 июля — Double Double\n"
        "Воскресенье, 26 июля — Mystery Bounty"
    )
    assert "•" not in answer.args[0]
    assert "Вход:" not in answer.args[0]
    assert "Ребаи:" not in answer.args[0]
    assert "Аддон:" not in answer.args[0]
    assert [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ] == ["Изменить", "Создать", "Отмена"]


def test_tournament_management_callback_routes_do_not_collide() -> None:
    top_level = keyboards.AdminCalendarCallback(
        action=keyboards.AdminCalendarAction.TOURNAMENTS
    ).pack()
    proposal_edit = keyboards.CalendarPromptCallback(
        action=keyboards.CalendarPromptAction.EDIT,
        prompt_id=8,
    ).pack()
    day_edit = keyboards.TournamentPromptDayEditCallback(
        prompt_id=8,
        tournament_date="2026-07-23",
    ).pack()
    type_edit = keyboards.TournamentTypeEditCallback(
        prompt_id=8,
        tournament_date="2026-07-23",
        tournament_type_id=2,
    ).pack()

    assert top_level.startswith("admin_calendar:")
    assert top_level == "admin_calendar:tournaments"
    assert proposal_edit.startswith("calendar_prompt:")
    assert day_edit.startswith("tour_prompt_day:")
    assert type_edit.startswith("tournament_type_edit:")
    assert len({top_level, proposal_edit, day_edit, type_edit}) == 4


async def test_admin_calendar_denies_regular_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(require_superadmin=AsyncMock(side_effect=AdminAccessDeniedError))
    monkeypatch.setattr(admin_handlers, "user_service", service)
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
    service = SimpleNamespace(require_superadmin=AsyncMock(side_effect=AdminAccessDeniedError))
    monkeypatch.setattr(admin_handlers, "user_service", service)
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


async def test_admin_calendar_prompt_reports_existing_tournament_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    calendar_service = SimpleNamespace(
        resolve_prompt=AsyncMock(side_effect=CalendarTournamentDateAlreadyExistsError)
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    message = SimpleNamespace(answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
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
    callback.answer.assert_awaited_once_with("На эту дату турнир уже создан.")
    message.answer.assert_awaited_once_with("На эту дату турнир уже создан.")


async def test_enter_season_proposal_name_returns_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    updated_proposal = SeasonProposalView(
        id=9,
        name="Осень 2026",
        starts_at=date(2026, 7, 28),
        scoring_config_id=1,
    )
    season_service = SimpleNamespace(
        update_season_proposal_name=AsyncMock(return_value=updated_proposal)
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="Осень 2026",
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"season_proposal_id": 9}),
        clear=AsyncMock(),
    )

    await admin_handlers.enter_season_proposal_name(message, state)

    season_service.update_season_proposal_name.assert_awaited_once_with(
        prompt_id=9,
        name="Осень 2026",
    )
    state.clear.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == ("🏆 Новый сезон\n\nНазвание: Осень 2026\nДата начала: 28 июля 2026")
    assert [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ] == ["✅ Создать", "✏️ Изменить", "❌ Отмена"]


async def test_enter_season_proposal_blank_name_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    season_service = SimpleNamespace(
        update_season_proposal_name=AsyncMock(side_effect=admin_handlers.SeasonNameInvalidError)
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="   ",
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"season_proposal_id": 9}),
        clear=AsyncMock(),
    )

    await admin_handlers.enter_season_proposal_name(message, state)

    state.clear.assert_not_awaited()
    message.answer.assert_awaited_once_with("Введи новое название сезона.")


async def test_tournament_edit_button_shows_day_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        get_tournament_prompt=AsyncMock(return_value=tournament_prompt_view())
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
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

    calendar_service.get_tournament_prompt.assert_awaited_once_with(8)
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0] == "Что меняем?"
    buttons = [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["Среда", "Четверг", "Пятница", "Суббота", "Воскресенье", "⬅️ Назад"]


async def test_stale_tournament_edit_callback_returns_stale_prompt_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        get_tournament_prompt=AsyncMock(side_effect=admin_handlers.CalendarPromptNotFoundError)
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(clear=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=SimpleNamespace(delete=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.CalendarPromptAction.EDIT,
        prompt_id=404,
    )

    await admin_handlers.review_calendar_prompt(callback, callback_data, state)

    callback.answer.assert_awaited_once_with(
        "Предложение устарело. Открой Турниры заново.",
        show_alert=True,
    )
    callback.message.answer.assert_not_awaited()


async def test_tournament_day_edit_back_button_returns_weekly_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    calendar_service = SimpleNamespace(
        get_tournament_prompt=AsyncMock(return_value=tournament_prompt_view())
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.CalendarPromptAction.BACK,
        prompt_id=8,
    )

    await admin_handlers.review_calendar_prompt(callback, callback_data, state)

    calendar_service.get_tournament_prompt.assert_awaited_once_with(8)
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0].startswith("Будет создано расписание:\n\n")
    assert [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ] == ["Изменить", "Создать", "Отмена"]


async def test_tournament_day_selection_shows_type_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    edit_view = TournamentPromptDayEditView(
        prompt_id=8,
        tournament_date=date(2026, 7, 22),
        tournament_types=[
            TournamentTypeOptionView(id=1, name="Баунти турнир"),
            TournamentTypeOptionView(id=2, name="Классика"),
        ],
    )
    calendar_service = SimpleNamespace(
        get_weekly_prompt_day_edit_options=AsyncMock(return_value=edit_view)
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        prompt_id=8,
        tournament_date="2026-07-22",
    )

    await admin_handlers.select_tournament_prompt_day(callback, callback_data, state)

    calendar_service.get_weekly_prompt_day_edit_options.assert_awaited_once_with(
        prompt_id=8,
        tournament_date=date(2026, 7, 22),
    )
    state.clear.assert_awaited_once()
    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == "Выбери тип турнира:\nСреда, 22 июля"
    assert [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ] == ["Баунти турнир", "Классика", "🗑 Удалить день", "⬅️ Назад"]


async def test_tournament_type_selection_redraws_prompt_without_type_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    updated_prompt = tournament_prompt_view(
        tournament_type=tournament_type_detail_view(
            type_id=4,
            name="Double Double",
            entry_fee=800,
            entry_stack=40_000,
            addon_fee=800,
            addon_stack=200_000,
            rebuys=[TournamentRebuyView(fee=800, stack=60_000)],
        )
    )
    calendar_service = SimpleNamespace(
        update_weekly_prompt_day_type=AsyncMock(return_value=updated_prompt)
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        prompt_id=8,
        tournament_date="2026-07-24",
        tournament_type_id=4,
    )

    await admin_handlers.select_tournament_type(callback, callback_data, state)

    calendar_service.update_weekly_prompt_day_type.assert_awaited_once_with(
        prompt_id=8,
        tournament_date=date(2026, 7, 24),
        tournament_type_id=4,
    )
    state.clear.assert_awaited_once()
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0] == (
        "Будет создано расписание:\n\n"
        "Среда, 22 июля — Double Double\n"
        "Четверг, 23 июля — Классика\n"
        "Пятница, 24 июля — Фризаут\n"
        "Суббота, 25 июля — Double Double\n"
        "Воскресенье, 26 июля — Mystery Bounty"
    )
    assert "Вход:" not in message.answer.await_args.args[0]
    assert "Ребаи:" not in message.answer.await_args.args[0]
    assert "Аддон:" not in message.answer.await_args.args[0]


async def test_tournament_day_removal_redraws_partial_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    updated_prompt = tournament_prompt_view(
        tournaments=[
            TournamentPromptItemView(
                date=date(2026, 7, 22),
                tournament_type=tournament_type_detail_view(type_id=1, name="Баунти турнир"),
            ),
            TournamentPromptItemView(
                date=date(2026, 7, 24),
                tournament_type=tournament_type_detail_view(type_id=3, name="Фризаут"),
            ),
        ]
    )
    calendar_service = SimpleNamespace(
        remove_weekly_prompt_day=AsyncMock(return_value=updated_prompt)
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        prompt_id=8,
        tournament_date="2026-07-23",
    )

    await admin_handlers.remove_tournament_prompt_day(callback, callback_data, state)

    calendar_service.remove_weekly_prompt_day.assert_awaited_once_with(
        prompt_id=8,
        tournament_date=date(2026, 7, 23),
    )
    state.clear.assert_awaited_once()
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0] == (
        "Будет создано расписание:\n\nСреда, 22 июля — Баунти турнир\nПятница, 24 июля — Фризаут"
    )
    assert [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ] == ["Изменить", "Создать", "Отмена"]


async def test_tournament_day_removal_rejects_empty_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    calendar_service = SimpleNamespace(
        remove_weekly_prompt_day=AsyncMock(
            side_effect=admin_handlers.CalendarWeeklyPromptEmptyError
        )
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "calendar_service", calendar_service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        prompt_id=8,
        tournament_date="2026-07-22",
    )

    await admin_handlers.remove_tournament_prompt_day(callback, callback_data, state)

    callback.answer.assert_awaited_once_with("В расписании должен остаться хотя бы один турнир.")
    message.answer.assert_awaited_once_with("В расписании должен остаться хотя бы один турнир.")


def test_tournament_economy_fsm_callbacks_are_removed() -> None:
    assert not hasattr(keyboards, "Tournament" + "EditAction")
    assert not hasattr(keyboards, "Tournament" + "OpenTypeCallback")
    assert not hasattr(admin_handlers, "CalendarTournament" + "OpenStates")
    assert not hasattr(admin_handlers, "enter_tournament" + "_date")
    assert not hasattr(admin_handlers, "enter_tournament" + "_edit_date")
    assert not hasattr(admin_handlers, "select_tournament" + "_open_type")
    assert not hasattr(admin_handlers, "select_tournament" + "_edit_field")
    assert not hasattr(admin_handlers, "CalendarTournament" + "EditStates")
    assert not hasattr(admin_handlers, "parse_tournament_economy")
    assert not hasattr(admin_handlers, "parse_tournament_rebuys")


async def test_season_change_button_shows_change_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.SeasonOpenAction.CHANGE,
        prompt_id=9,
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.select_season_open_action(callback, callback_data, state)

    state.clear.assert_awaited_once()
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0] == "Что меняем?"
    assert [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ] == ["✏️ Название", "📅 Дата начала", "⬅️ Назад"]


async def test_season_change_name_button_prompts_for_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.SeasonOpenAction.NAME,
        prompt_id=9,
    )
    state = SimpleNamespace(set_state=AsyncMock(), update_data=AsyncMock())

    await admin_handlers.select_season_open_action(callback, callback_data, state)

    state.set_state.assert_awaited_once_with(
        admin_handlers.CalendarSeasonProposalEditStates.entering_name
    )
    state.update_data.assert_awaited_once_with(season_proposal_id=9)
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with("Введи новое название сезона.")


async def test_season_change_back_returns_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    season_service = SimpleNamespace(
        get_season_proposal=AsyncMock(return_value=season_proposal_view())
    )
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.SeasonOpenAction.BACK,
        prompt_id=9,
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.select_season_open_action(callback, callback_data, state)

    season_service.get_season_proposal.assert_awaited_once_with(9)
    state.clear.assert_awaited_once()
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0].startswith("🏆 Новый сезон\n\n")


async def test_enter_season_proposal_start_date_returns_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    updated_proposal = SeasonProposalView(
        id=9,
        name="Лето 2026",
        starts_at=date(2026, 9, 1),
        scoring_config_id=1,
    )
    season_service = SimpleNamespace(
        update_season_proposal_start_date=AsyncMock(return_value=updated_proposal)
    )
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="1.09.2026",
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"season_proposal_id": 9}),
        clear=AsyncMock(),
    )

    await admin_handlers.enter_season_proposal_starts_at(message, state)

    season_service.update_season_proposal_start_date.assert_awaited_once_with(
        prompt_id=9,
        starts_at=date(2026, 9, 1),
    )
    state.clear.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == ("🏆 Новый сезон\n\nНазвание: Лето 2026\nДата начала: 1 сентября 2026")


async def test_cancel_season_proposal_discards_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    season_service = SimpleNamespace(cancel_season_proposal=AsyncMock())
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.SeasonOpenAction.CANCEL,
        prompt_id=9,
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.select_season_open_action(callback, callback_data, state)

    season_service.cancel_season_proposal.assert_awaited_once_with(
        admin_telegram_id=100,
        prompt_id=9,
    )
    state.clear.assert_awaited_once()
    callback.answer.assert_awaited_once_with("Отмена.")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with("Отмена.")


async def test_confirm_season_proposal_calls_public_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    season_service = SimpleNamespace(
        confirm_season_proposal=AsyncMock(return_value=season_view()),
    )
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.SeasonOpenAction.CONFIRM,
        prompt_id=9,
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.select_season_open_action(callback, callback_data, state)

    season_service.confirm_season_proposal.assert_awaited_once_with(
        admin_telegram_id=100,
        prompt_id=9,
    )
    state.clear.assert_awaited_once_with()
    callback.answer.assert_awaited_once_with("Сезон создан.")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with(
        "Создан новый сезон:\nОсень 2026\nДата начала: 1.09.2026\nКонфигурация рейтинга: #1"
    )


async def test_confirm_season_proposal_name_conflict_keeps_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    season_service = SimpleNamespace(
        confirm_season_proposal=AsyncMock(side_effect=admin_handlers.SeasonNameAlreadyExistsError)
    )
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=SimpleNamespace(delete=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.select_season_open_action(
        callback,
        SimpleNamespace(action=keyboards.SeasonOpenAction.CONFIRM, prompt_id=9),
        state,
    )

    callback.answer.assert_awaited_once_with(
        "Сезон с таким названием уже существует.",
        show_alert=True,
    )
    state.clear.assert_not_awaited()


async def test_repeat_season_confirm_callback_does_not_create_second_season(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    season_service = SimpleNamespace(
        confirm_season_proposal=AsyncMock(
            side_effect=admin_handlers.SeasonProposalAlreadyResolvedError
        )
    )
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=SimpleNamespace(delete=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_handlers.select_season_open_action(
        callback,
        SimpleNamespace(action=keyboards.SeasonOpenAction.CONFIRM, prompt_id=9),
        state,
    )

    season_service.confirm_season_proposal.assert_awaited_once()
    callback.answer.assert_awaited_once_with(
        "Сценарий открытия сезона уже завершён.",
        show_alert=True,
    )


async def test_enter_season_start_rejects_invalid_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    season_service = SimpleNamespace(update_season_proposal_start_date=AsyncMock())
    monkeypatch.setattr(admin_handlers, "user_service", user_service)
    monkeypatch.setattr(admin_handlers, "season_service", season_service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="2026-09-01",
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"season_proposal_id": 9}),
        clear=AsyncMock(),
    )

    await admin_handlers.enter_season_proposal_starts_at(message, state)

    season_service.update_season_proposal_start_date.assert_not_awaited()
    state.clear.assert_not_awaited()
    message.answer.assert_awaited_once_with("Дата должна быть в формате 1.09.2026.")


async def test_admin_panel_registration_requests_button_shows_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    service = SimpleNamespace(
        require_superadmin=AsyncMock(),
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[])),
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.show_pending_registrations(message)

    service.require_superadmin.assert_awaited_once_with(100)
    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once_with("Новых заявок нет.")


async def test_admin_panel_registration_requests_button_shows_paginated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    reviews = [registration_review(player_id) for player_id in range(10, 17)]
    service = SimpleNamespace(
        require_superadmin=AsyncMock(),
        get_admin_panel_for_admin=AsyncMock(
            return_value=AdminPanelView(admin=admin, reviews=reviews)
        ),
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
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
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == ["10", "11", "12", "13", "14", "15", "➡️", "❌ Отмена"]


async def test_admin_registration_list_page_callback_edits_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    reviews = [registration_review(player_id) for player_id in range(10, 17)]
    service = SimpleNamespace(
        require_superadmin=AsyncMock(),
        get_admin_panel_for_admin=AsyncMock(
            return_value=AdminPanelView(admin=admin, reviews=reviews)
        ),
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
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

    service.require_superadmin.assert_awaited_once_with(100)
    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == (
        "Заявки на регистрацию\n\n16 — Игрок 16\n\nСтраница 2/2"
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
    service = SimpleNamespace(get_registration_review_for_admin=AsyncMock(return_value=review))
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationListAction.OPEN,
        page=0,
        request_id=10,
    )

    await admin_handlers.review_registration_list(callback, callback_data)

    service.get_registration_review_for_admin.assert_awaited_once_with(
        admin_telegram_id=100,
        request_id=10,
    )
    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()
    assert "Новая заявка на регистрацию" in message.edit_text.await_args.args[0]
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["✏️ Изменить имя", "✅ Одобрить", "🚫 Отклонить", "❌ Отмена"]


async def test_admin_panel_exit_returns_main_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRoleView.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[]))
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
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
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_handlers.open_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once_with("У тебя нет доступа в админ-панель!")


async def test_registration_review_keyboard_with_history_has_action_labels() -> None:
    keyboard = keyboards.registration_review_keyboard(
        request_id=10,
        can_edit_name=True,
        can_select_candidate=True,
    )

    buttons = [button.text for row in keyboard.inline_keyboard for button in row]
    assert buttons == [
        "🔗 Выбрать игрока",
        "✏️ Изменить имя",
        "✅ Одобрить",
        "🚫 Отклонить",
        "❌ Отмена",
    ]
    assert [len(row) for row in keyboard.inline_keyboard] == [1, 1, 1, 1, 1]


async def test_registration_review_cancel_deletes_message_without_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        approve_registration=AsyncMock(),
        reject_registration=AsyncMock(),
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(delete=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=keyboards.RegistrationReviewAction.CANCEL,
        request_id=10,
    )

    await admin_handlers.review_registration(callback, callback_data)

    callback.answer.assert_awaited_once_with("Заявка скрыта")
    message.delete.assert_awaited_once()
    service.approve_registration.assert_not_awaited()
    service.reject_registration.assert_not_awaited()


async def test_registration_review_reject_deletes_pending_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = RegistrationRequestView(
        id=10,
        telegram_id=200,
        request_type="new_player",
        status="rejected",
        requested_display_name="Игрок Второй",
        requested_link_name=None,
        candidate_user_id=None,
        created_at="27.07.2026 12:00",
    )
    reviewer = admin_player(1, 100, UserRoleView.SUPERADMIN)
    other_admin = admin_player(2, 101)
    service = SimpleNamespace(
        reject_registration=AsyncMock(
            return_value=RegistrationReviewResultView(
                user=None,
                request=request,
                admins=[reviewer, other_admin],
            )
        )
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
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
        request_id=10,
    )

    await admin_handlers.review_registration(callback, callback_data)

    service.reject_registration.assert_awaited_once_with(
        superadmin_telegram_id=100,
        request_id=10,
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
    review = RegistrationReviewView(
        request=registration_review(10).request,
        candidates=matches,
    )
    service = SimpleNamespace(
        get_registration_review_for_admin=AsyncMock(return_value=review),
        approve_registration=AsyncMock(),
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
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
        action=keyboards.RegistrationReviewAction.SELECT_CANDIDATE,
        request_id=10,
    )

    await admin_handlers.review_registration(callback, callback_data)

    service.get_registration_review_for_admin.assert_awaited_once_with(
        admin_telegram_id=100,
        request_id=10,
    )
    service.approve_registration.assert_not_awaited()
    callback.answer.assert_awaited_once_with()
    message.edit_reply_markup.assert_awaited_once()
    selection_keyboard = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    buttons = [button.text for row in selection_keyboard.inline_keyboard for button in row]
    assert buttons == [
        "1. Исторический 20 (100%)",
        "2. Исторический 21 (92%)",
        "✅ Одобрить",
        "🚫 Отклонить",
        "❌ Отмена",
    ]


async def test_selected_registration_candidate_is_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = RegistrationReviewView(
        request=RegistrationRequestView(
            id=10,
            telegram_id=200,
            request_type="link_existing_player",
            status="pending",
            requested_display_name=None,
            requested_link_name="Исторический",
            candidate_user_id=21,
            created_at="27.07.2026 12:00",
        ),
        candidates=[registration_match(21, 100)],
    )
    service = SimpleNamespace(select_registration_candidate=AsyncMock(return_value=review))
    monkeypatch.setattr(admin_handlers, "user_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_text=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(request_id=10, user_id=21)

    await admin_handlers.select_registration_candidate(callback, callback_data)

    service.select_registration_candidate.assert_awaited_once_with(
        superadmin_telegram_id=100,
        request_id=10,
        user_id=21,
    )
    message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once_with("Игрок выбран.")


async def test_registration_review_result_is_sent_to_other_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = UserView(
        id=10,
        telegram_id=200,
        display_name="Игрок Второй",
        status=UserStatusView.ACTIVE,
        role=UserRoleView.ADMIN,
    )
    reviewer = admin_player(1, 100, UserRoleView.SUPERADMIN)
    other_admin = admin_player(2, 101)
    service = SimpleNamespace(
        approve_registration=AsyncMock(
            return_value=RegistrationReviewResultView(
                user=player,
                request=RegistrationRequestView(
                    id=10,
                    telegram_id=200,
                    request_type="new_player",
                    status="approved",
                    requested_display_name="Игрок Второй",
                    requested_link_name=None,
                    candidate_user_id=None,
                    created_at="27.07.2026 12:00",
                ),
                admins=[reviewer, other_admin],
            )
        ),
    )
    monkeypatch.setattr(admin_handlers, "user_service", service)
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
        request_id=10,
    )

    await admin_handlers.review_registration(callback, callback_data)

    service.approve_registration.assert_awaited_once_with(
        superadmin_telegram_id=100,
        request_id=10,
    )
    message.edit_text.assert_awaited_once()
    assert callback.answer.await_args.args[0] == "Заявка одобрена"
    assert bot.send_message.await_count == 2
    admin_call, player_call = bot.send_message.await_args_list
    assert admin_call.kwargs["chat_id"] == 101
    assert "Заявка одобрена: Админ 1" in admin_call.kwargs["text"]
    assert player_call.kwargs["chat_id"] == 200
    assert player_call.kwargs["text"] == "Ваша заявка одобрена."
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
