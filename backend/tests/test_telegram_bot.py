import asyncio
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import (
    Chat,
    Message,
)
from conftest import build_player, seed_tournament_types_async, tournament_type_id
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api import telegram_webhook as webhook_module
from app.bot.telegram import notifications, runtime
from app.bot.telegram.formatters import check_in as check_in_fmt
from app.bot.telegram.formatters import common as fmt_common
from app.bot.telegram.formatters import results as result_fmt
from app.bot.telegram.formatters import seasons as season_fmt
from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.bot.telegram.handlers import admin as admin_handlers
from app.bot.telegram.handlers import superadmin as superadmin_handlers
from app.bot.telegram.handlers import user as user_handlers
from app.bot.telegram.handlers.admin import calendar as admin_calendar_handlers
from app.bot.telegram.handlers.admin import check_in as admin_check_in_handlers
from app.bot.telegram.handlers.admin import panel as admin_panel_handlers
from app.bot.telegram.handlers.admin import results as admin_result_handlers
from app.bot.telegram.handlers.admin import schedule as admin_schedule_handlers
from app.bot.telegram.handlers.superadmin import administrators as superadmin_administrator_handlers
from app.bot.telegram.handlers.superadmin import hall_of_fame as superadmin_hall_of_fame_handlers
from app.bot.telegram.handlers.superadmin import panel as superadmin_panel_handlers
from app.bot.telegram.handlers.superadmin import registrations as superadmin_registration_handlers
from app.bot.telegram.handlers.superadmin import seasons as superadmin_season_handlers
from app.bot.telegram.handlers.superadmin import tournament_close as superadmin_close_handlers
from app.bot.telegram.handlers.superadmin import users as superadmin_user_handlers
from app.bot.telegram.handlers.user import hall_of_fame as user_hall_of_fame_handlers
from app.bot.telegram.handlers.user import history as user_history_handlers
from app.bot.telegram.handlers.user import profile as user_profile_handlers
from app.bot.telegram.handlers.user import rating as user_rating_handlers
from app.bot.telegram.handlers.user import registration as user_registration_handlers
from app.bot.telegram.handlers.user import start as user_start_handlers
from app.bot.telegram.handlers.user import tournaments as user_tournament_handlers
from app.bot.telegram.keyboards import labels
from app.bot.telegram.keyboards.admin import calendar as admin_calendar_kb
from app.bot.telegram.keyboards.admin import check_in as admin_check_in_kb
from app.bot.telegram.keyboards.admin import results as admin_results_kb
from app.bot.telegram.keyboards.admin import schedule as admin_schedule_kb
from app.bot.telegram.keyboards.superadmin import administrators as superadmin_administrators_kb
from app.bot.telegram.keyboards.superadmin import hall_of_fame as superadmin_hall_of_fame_kb
from app.bot.telegram.keyboards.superadmin import registrations as superadmin_registrations_kb
from app.bot.telegram.keyboards.superadmin import seasons as superadmin_seasons_kb
from app.bot.telegram.keyboards.superadmin import tournament_close as superadmin_tournament_close_kb
from app.bot.telegram.keyboards.superadmin import users as superadmin_users_kb
from app.bot.telegram.keyboards.user import profile as user_profile_kb
from app.bot.telegram.keyboards.user import rating as user_rating_kb
from app.bot.telegram.keyboards.user import tournaments as user_tournaments_kb
from app.bot.telegram.states import AdminResultStates, HallOfFameStates, UserRenameStates
from app.bot.telegram.texts.admin import results as admin_result_text
from app.bot.telegram.texts.user import registration as registration_text
from app.bot.telegram.texts.user import tournaments as tournament_text
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.factories import create_user
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentPhoto,
    TournamentRegistration,
    TournamentResult,
    User,
)
from app.db.models.enums import TournamentResultSource, TournamentStatus, UserRole, UserStatus
from app.db.repositories.tournament_photo_repository import TournamentPhotoRepository
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.hall_of_fame import (
    HallOfFameCandidateView,
    HallOfFameEntryView,
    HallOfFameSeasonListItemView,
)
from app.services.dto.registrations import (
    AdminPanelView,
    RegistrationCandidateView,
    RegistrationNotificationView,
    RegistrationRequestView,
    RegistrationReviewResultView,
    RegistrationReviewView,
    RegistrationsOverviewView,
    TournamentRegistrationCountView,
)
from app.services.dto.results import (
    TournamentCloseReadinessView,
    TournamentResultPlayerView,
    TournamentResultsView,
)
from app.services.dto.schedules import (
    TournamentPlanDayEditView,
    TournamentPlanItemView,
    TournamentRebuyView,
    TournamentTypeDetailView,
    TournamentTypeOptionView,
    WeeklyScheduleTournamentView,
    WeeklyScheduleView,
    WeeklyTournamentFactItemView,
    WeeklyTournamentFactView,
    WeeklyTournamentPlanView,
)
from app.services.dto.seasons import (
    ScoringConfigView,
    SeasonCreationPreviewView,
    SeasonLifecycleStateView,
    SeasonOptionView,
    SeasonTimelineView,
    SeasonView,
)
from app.services.dto.statistics.hall_of_fame import HallOfFameSeasonView
from app.services.dto.statistics.history import (
    HistoricalTournamentResultRowView,
    HistoricalTournamentResultView,
    HistoricalTournamentView,
    HistoryMonthView,
    HistoryYearView,
)
from app.services.dto.statistics.profile import PlayerPrizeTournamentView, PlayerProfileView
from app.services.dto.statistics.rating import PointsRatingView, RatingResultView
from app.services.dto.tournaments import TournamentView
from app.services.dto.users import UserStartStatusView, UserStartView, UserView
from app.services.pagination import Page
from app.services.profile_service import ProfileKind
from app.services.rating_service import RatingKind
from app.services.result_service import FutureTournamentCannotBeClosedError, ResultService
from app.services.tournament_check_in_service import TournamentCheckInService
from app.services.tournament_planning_service import (
    WeeklyPlanningCheckView,
    WeeklyPlanningStatus,
)
from app.services.tournament_service import TournamentRegistrationAlreadyCheckedInError
from app.services.user_access_service import UserAccessService


class RecordingBot(Bot):
    def __init__(self) -> None:
        super().__init__("123456:TEST")
        self.calls: list[object] = []

    async def __call__(self, method: object, request_timeout: int | None = None) -> object:
        self.calls.append(method)
        if method.__class__.__name__ == "SendMessage":
            return Message(
                message_id=len(self.calls) + 100,
                date=datetime(2026, 7, 29, 12, 0),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        return True


async def _build_photo_collection_service(
    database_path: Path,
    *,
    telegram_id: int,
    role: UserRole,
) -> tuple[ResultService, AsyncEngine, int]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        admin = build_player(
            telegram_id=telegram_id,
            display_name="Photo Admin",
            status=UserStatus.ACTIVE,
            role=role,
        )
        session.add_all([season, admin])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        tournament_id = tournament.id
        await session.commit()

    return (
        ResultService(
            session_factory,
            clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
        ),
        engine,
        tournament_id,
    )


def _photo_callback_update(update_id: int, *, user_id: int, data: str) -> dict[str, object]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"photo-callback-{update_id}",
            "from": {"id": user_id, "is_bot": False, "first_name": "Admin"},
            "message": {
                "message_id": update_id + 1000,
                "date": 1783598400,
                "chat": {"id": user_id, "type": "private"},
                "text": "Фото",
            },
            "chat_instance": "chat-instance",
            "data": data,
        },
    }


def _photo_message_update(
    update_id: int,
    *,
    user_id: int,
    file_id: str,
    unique_id: str,
    media_group_id: str | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {
        "message_id": update_id + 1000,
        "date": 1783598400,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Admin"},
        "photo": [
            {
                "file_id": file_id,
                "file_unique_id": unique_id,
                "width": 1,
                "height": 1,
            }
        ],
    }
    if media_group_id is not None:
        message["media_group_id"] = media_group_id
    return {"update_id": update_id, "message": message}


def active_player() -> UserView:
    return UserView(
        id=1,
        telegram_id=123,
        display_name="Игрок Первый",
        status=UserStatus.ACTIVE,
        role=UserRole.PLAYER,
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


def season_creation_preview_view() -> SeasonCreationPreviewView:
    return SeasonCreationPreviewView(
        name="Лето 2026",
        starts_at=date(2026, 7, 28),
        scoring_config_id=1,
    )


def season_timeline_view() -> SeasonTimelineView:
    return SeasonTimelineView(
        completed_seasons=[],
        current_season=SeasonView(
            id=1,
            name="Лето 2026",
            starts_at=date(2026, 6, 1),
            ends_at=None,
            lifecycle_state=SeasonLifecycleStateView.CURRENT,
            scoring_config_id=1,
        ),
        future_seasons=[],
        suggested_start=None,
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


def tournament_plan_view(
    *,
    tournament_type: TournamentTypeDetailView | None = None,
    tournaments: list[TournamentPlanItemView] | None = None,
) -> WeeklyTournamentPlanView:
    tournament_items = tournaments or [
        TournamentPlanItemView(
            date=date(2026, 7, 22),
            tournament_type=tournament_type or tournament_type_detail_view(),
        ),
        TournamentPlanItemView(
            date=date(2026, 7, 23),
            tournament_type=tournament_type_detail_view(
                type_id=2,
                name="Классика",
            ),
        ),
        TournamentPlanItemView(
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
        TournamentPlanItemView(
            date=date(2026, 7, 25),
            tournament_type=tournament_type_detail_view(
                type_id=4,
                name="Double Double",
            ),
        ),
        TournamentPlanItemView(
            date=date(2026, 7, 26),
            tournament_type=tournament_type_detail_view(
                type_id=5,
                name="Mystery Bounty",
                knockout_mode="mystery",
            ),
        ),
    ]
    return WeeklyTournamentPlanView(
        week_start=tournament_items[0].date,
        week_end=tournament_items[-1].date,
        tournaments=tournament_items,
    )


def weekly_fact_view(
    names: list[str | None] | None = None,
) -> WeeklyTournamentFactView:
    tournament_names = names or [
        "Баунти турнир",
        "Классика",
        "Фризаут",
        "Double Double",
        "Boss Bounty",
    ]
    dates = [
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
        date(2026, 8, 15),
        date(2026, 8, 16),
    ]
    return WeeklyTournamentFactView(
        week_start=dates[0],
        week_end=dates[-1],
        tournaments=[
            WeeklyTournamentFactItemView(
                date=tournament_date,
                tournament_type_name=tournament_name,
            )
            for tournament_date, tournament_name in zip(dates, tournament_names, strict=True)
        ],
    )


def test_parse_result_manual_value() -> None:
    assert (
        admin_result_handlers.parse_result_manual_value(
            "17",
            field=admin_results_kb.AdminResultField.KNOCKOUTS,
        )
        == 17
    )
    assert (
        admin_result_handlers.parse_result_manual_value(
            "10",
            field=admin_results_kb.AdminResultField.BIG_KNOCKOUTS,
        )
        == 10
    )
    assert (
        admin_result_handlers.parse_result_manual_value(
            "5",
            field=admin_results_kb.AdminResultField.PLACE,
        )
        == 5
    )


def test_parse_result_manual_value_rejects_place_outside_top_five() -> None:
    with pytest.raises(ValueError):
        admin_result_handlers.parse_result_manual_value(
            "6",
            field=admin_results_kb.AdminResultField.PLACE,
        )


def first_code_block_lines(text: str) -> list[str]:
    return text.split("```", maxsplit=2)[1].strip("\n").splitlines()


def test_admin_result_players_hide_ids_and_empty_places() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    players = [
        TournamentResultPlayerView(
            player_id=252,
            display_name="Тест Игрок",
            place=None,
            knockouts_count=0,
            big_knockouts_count=0,
        ),
        TournamentResultPlayerView(
            player_id=108,
            display_name="Илларионов Александр",
            place=2,
            knockouts_count=0,
            big_knockouts_count=0,
        ),
    ]
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=players,
        knockout_mode="none",
    )
    page = Page(items=players, page=0, page_size=6, total_items=2)

    text = result_fmt.players_table(results, page)
    assert text.startswith("Игроки турнира\nВоскресенье, 19 июля — Классика\n\nИгроки: 2")
    assert "В " + "работе" not in text
    table_lines = first_code_block_lines(text)
    assert table_lines[0] == "№ Игрок"
    assert "КО" not in text
    assert "БКО" not in text
    assert "Бонус" not in text
    assert "2 Илларионов" in text
    assert "Тест Игрок" not in text
    buttons = [
        button.text
        for row in admin_results_kb.admin_result_players_keyboard(results, page).inline_keyboard
        for button in row
    ]
    assert buttons == [
        "Тест Игрок",
        "Илларионов Александр: 2️⃣",
        "❌ Отмена",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (1, "1"),
        (Decimal("1.4"), "1"),
        (Decimal("1.5"), "2"),
        (Decimal("2.5"), "3"),
        (Decimal("88.49"), "88"),
        (Decimal("88.50"), "89"),
        (Decimal("1347.5"), "1348"),
        (1.5, "2"),
    ],
)
def test_common_points_formatter_uses_half_up_rounding(
    value: object,
    expected: str,
) -> None:
    assert fmt_common.points(value) == expected


def test_admin_result_players_show_empty_state_without_entered_results() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    players = [
        TournamentResultPlayerView(
            player_id=252,
            display_name="Тест Игрок",
            place=None,
            knockouts_count=0,
            big_knockouts_count=0,
        )
    ]
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=players,
        knockout_mode="none",
    )
    page = Page(items=players, page=0, page_size=6, total_items=1)

    text = result_fmt.players_table(results, page)
    assert "Игроки: 1" in text
    assert "В " + "работе" not in text
    assert first_code_block_lines(text)[0] == "№ Игрок"
    assert "Тест Игрок" not in text


def test_admin_result_player_buttons_show_entered_knockouts_and_place() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    players = [
        TournamentResultPlayerView(
            player_id=108,
            display_name="Илларионов Александр",
            place=2,
            knockouts_count=3,
            big_knockouts_count=1,
        ),
        TournamentResultPlayerView(
            player_id=252,
            display_name="Тест Игрок",
            place=None,
            knockouts_count=0,
            big_knockouts_count=0,
        ),
    ]
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=players,
        knockout_mode="small_big",
    )
    page = Page(items=players, page=0, page_size=6, total_items=2)

    buttons = [
        button.text
        for row in admin_results_kb.admin_result_players_keyboard(results, page).inline_keyboard
        for button in row
    ]

    assert buttons == [
        "Илларионов Александр: 2️⃣ | 👑🥊 х1 | 🥊 х3",
        "Тест Игрок",
        "❌ Отмена",
    ]


def test_admin_result_root_keyboard_has_data_photos_cancel_only() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=[],
        knockout_mode="small_big",
        photo_count=2,
    )

    assert result_fmt.management_root(results).startswith("🏁 Внести результаты\n\n")
    assert inline_keyboard_texts(admin_results_kb.admin_result_root_keyboard(results)) == [
        "🏁 Внести данные",
        "📸 Фотографии",
        "❌ Отмена",
    ]


def test_admin_result_data_keyboard_has_players_back_cancel_without_photo_actions() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=[
            TournamentResultPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            )
        ],
        knockout_mode="small_big",
        photo_count=2,
    )
    page = Page(items=results.players, page=0, page_size=6, total_items=1)

    buttons = inline_keyboard_texts(
        admin_results_kb.admin_result_players_keyboard(
            results,
            page,
            back_callback=admin_results_kb.AdminResultMenuCallback(
                action=admin_results_kb.AdminResultMenuAction.ROOT,
                tournament_id=results.tournament.id,
            ),
        )
    )

    assert buttons == ["Илларионов Александр", "⬅️ Назад", "❌ Отмена"]


def test_admin_result_photo_menu_buttons_for_empty_and_existing_photos() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    empty_results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=[],
        knockout_mode="small_big",
        photo_count=0,
    )
    filled_results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=[],
        knockout_mode="small_big",
        photo_count=2,
    )
    back_callback = admin_results_kb.AdminResultMenuCallback(
        action=admin_results_kb.AdminResultMenuAction.ROOT,
        tournament_id=tournament.id,
    )

    assert inline_keyboard_texts(
        admin_results_kb.admin_result_photo_menu_keyboard(
            empty_results,
            back_callback=back_callback,
        )
    ) == ["📸 Добавить фото", "⬅️ Назад", "❌ Отмена"]
    assert inline_keyboard_texts(
        admin_results_kb.admin_result_photo_menu_keyboard(
            filled_results,
            back_callback=back_callback,
        )
    ) == [
        "📸 Добавить фото",
        "🖼 Посмотреть фото (2)",
        "🗑 Удалить все фото",
        "⬅️ Назад",
        "❌ Отмена",
    ]


def test_admin_result_players_show_place_only_table_for_classic() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=2200,
        players=[
            TournamentResultPlayerView(
                player_id=255,
                display_name="Тест Игрок 4",
                place=2,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=1,
                display_name="Дима Боченков",
                place=4,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=252,
                display_name="Тест Игрок 1",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=258,
                display_name="Тест Игрок 7",
                place=5,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
        ],
        knockout_mode="none",
    )

    page = Page(items=results.players, page=0, page_size=6, total_items=5)
    text = result_fmt.players_table(results, page)

    table_lines = first_code_block_lines(text)
    assert table_lines[0] == "№ Игрок"
    assert "КО" not in text
    assert "БКО" not in text
    assert "Бонус" not in text
    assert "1 Тест Игрок 1" in text
    assert "2 Тест Игрок 4" in text
    assert "4 Дима Боченков" in text
    assert "5 Тест Игрок 7" in text
    assert "Илларионов Александр" not in text
    assert all(len(line) <= result_fmt.GAME_TABLE_TOTAL_WIDTH for line in table_lines)


def test_admin_result_players_show_required_place_slots() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=2200,
        players=[
            TournamentResultPlayerView(
                player_id=1,
                display_name="Первый",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=2,
                display_name="Четвертый",
                place=4,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=3,
                display_name="Без результата",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=4,
                display_name="КО без места",
                place=None,
                knockouts_count=3,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=5,
                display_name="Пятый",
                place=5,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
        ],
        knockout_mode="small",
    )
    page = Page(items=results.players, page=0, page_size=6, total_items=5)

    text = result_fmt.players_table(results, page)

    assert "1 Первый" in text
    assert "2 НЕ ВВЕДЕНО" in text
    assert "3 НЕ ВВЕДЕНО" in text
    assert "4 Четвертый" in text
    assert "5 Пятый" in text
    assert "— КО без места" in text
    assert "Без результата" not in text


def test_admin_result_players_add_knockout_columns_for_bounty() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=2200,
        players=[
            TournamentResultPlayerView(
                player_id=1,
                display_name="Игрок КО",
                place=None,
                knockouts_count=4,
                big_knockouts_count=1,
            ),
            TournamentResultPlayerView(
                player_id=2,
                display_name="Игрок БКО",
                place=None,
                knockouts_count=1,
                big_knockouts_count=2,
            ),
            TournamentResultPlayerView(
                player_id=3,
                display_name="Игрок Место",
                place=3,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
            TournamentResultPlayerView(
                player_id=4,
                display_name="Игрок Много КО",
                place=None,
                knockouts_count=7,
                big_knockouts_count=1,
            ),
        ],
        knockout_mode="small_big",
    )

    page = Page(items=results.players, page=0, page_size=6, total_items=4)
    text = result_fmt.players_table(results, page)

    table_lines = first_code_block_lines(text)
    assert table_lines[0] == "№ Игрок                         КО БКО"
    assert "🥊" not in table_lines[0]
    assert "👑" not in table_lines[0]
    assert "Бонус" not in text
    assert "3 Игрок Место" in text
    assert "— Игрок БКО" in text
    assert "Игрок КО" in text
    assert "Игрок Много КО" in text
    assert all(len(line) <= result_fmt.GAME_TABLE_TOTAL_WIDTH for line in table_lines)


def test_admin_result_players_add_bonus_only_when_supported() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=2200,
        players=[
            TournamentResultPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            )
        ],
        knockout_mode="small",
        supports_bonus_points=True,
    )
    page = Page(items=results.players, page=0, page_size=6, total_items=1)

    text = result_fmt.players_table(results, page)
    assert first_code_block_lines(text)[0] == "№ Игрок                       КО Бонус"
    assert "КО" in text
    assert "Бонус" in text
    assert "БКО" not in text
    assert "Илларионов Александр" not in text


def test_mystery_bounty_result_ui_uses_bonus_without_knockouts() -> None:
    tournament = tournament_view(
        125,
        date(2026, 7, 19),
        5,
        "Mystery Bounty",
        "mystery_bounty",
    )
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=2200,
        players=[
            TournamentResultPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=1,
                knockouts_count=3,
                big_knockouts_count=2,
                bonus_points=7,
                tournament_points=Decimal("100"),
            ),
            TournamentResultPlayerView(
                player_id=109,
                display_name="Пустой",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
        ],
        knockout_mode="none",
        supports_bonus_points=True,
    )
    page = Page(items=results.players, page=0, page_size=6, total_items=2)

    text = result_fmt.players_table(results, page)
    field_buttons = inline_keyboard_texts(
        admin_results_kb.admin_result_player_fields_keyboard(
            results,
            results.players[0],
            page=0,
        )
    )
    close_preview = result_fmt.closed_tournament(results)

    assert "КО" not in text
    assert "БКО" not in text
    assert "Доп. очки" in text
    assert "1 Илларионов" in text
    assert "2 НЕ ВВЕДЕНО" in text
    assert field_buttons == ["➕ Доп. очки", "🏁 Место", "❌ Отмена"]
    assert "КО" not in close_preview
    assert "БКО" not in close_preview
    assert "Доп. очки" in close_preview
    assert "Очки" in close_preview


def test_admin_close_tournament_formatters_show_fund_and_game_tables() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=[
            TournamentResultPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=2,
                knockouts_count=3,
                big_knockouts_count=1,
                bonus_points=5,
                tournament_points=Decimal("1000.50"),
                knockout_points=Decimal("105"),
            ),
            TournamentResultPlayerView(
                player_id=252,
                display_name="Тест Игрок",
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
        ],
        knockout_mode="small_big",
        supports_bonus_points=True,
    )

    card = result_fmt.close_tournament_card(results)
    confirmation = result_fmt.close_tournament_confirmation(results, 1800)
    closed = result_fmt.closed_tournament(results)

    assert result_fmt.tournament_fund_prompt() == "Введите фонд турнира."
    assert result_fmt.tournament_fund_error_prompt() == (
        "Фонд турнира должен быть положительным целым числом, кратным 10.\n\nВведите фонд турнира."
    )
    assert "Введите фонд турнира?" in card
    assert "№ Игрок                   КО БКО Бонус" in card
    assert "Бонус" in card
    assert "🥊" not in first_code_block_lines(card)[0]
    assert "Фонд турнира: 1800" in confirmation
    assert "После подтверждения будут рассчитаны рейтинговые очки" in confirmation
    assert "✅ Турнир закрыт" in closed
    assert "№ Игрок              КО БКО Бонус Очки" in closed
    assert "Бонус" in closed
    assert "Очки" in closed
    assert "1111" in closed
    assert "1110.5" not in closed
    assert "Тест Игрок" not in card
    assert "Тест Игрок" not in confirmation
    assert "Тест Игрок" not in closed
    assert all(
        len(line) <= result_fmt.GAME_TABLE_TOTAL_WIDTH for line in first_code_block_lines(card)
    )
    assert all(
        len(line) <= result_fmt.GAME_TABLE_TOTAL_WIDTH for line in first_code_block_lines(closed)
    )


def test_admin_close_tournament_fund_input_keyboard_has_back_and_cancel() -> None:
    keyboard = superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
        tournament_id=125,
        page=0,
    )

    assert inline_keyboard_texts(keyboard) == ["⬅️ Назад", "❌ Отмена"]


def test_superadmin_repair_root_keyboard_has_back_and_cancel() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    readiness = SimpleNamespace(tournament=tournament, photo_count=3)

    keyboard = superadmin_tournament_close_kb.admin_correction_tournament_card_keyboard(readiness)

    assert inline_keyboard_texts(keyboard) == [
        "👤 Добавить игрока",
        "🏁 Внести данные",
        "📸 Фотографии",
        "⬅️ Назад",
        "❌ Отмена",
    ]


def test_superadmin_correction_list_keyboard_has_back_and_cancel() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    readiness = SimpleNamespace(tournament=tournament, is_ready=True)
    page = Page(items=[readiness], page=0, page_size=6, total_items=1)

    keyboard = superadmin_tournament_close_kb.admin_correction_tournament_list_keyboard(page)

    assert inline_keyboard_texts(keyboard) == [
        "✅ 19.07 — Boss Bounty",
        "⬅️ Назад",
        "❌ Отмена",
    ]


def test_superadmin_repair_nested_keyboards_keep_back_and_cancel() -> None:
    player = SimpleNamespace(id=42, display_name="Игрок")

    assert inline_keyboard_texts(
        superadmin_tournament_close_kb.admin_repair_add_player_mode_keyboard(125)
    ) == ["👤 Играл ранее", "🆕 Новый игрок", "⬅️ Назад", "❌ Отмена"]
    assert inline_keyboard_texts(
        superadmin_tournament_close_kb.admin_repair_search_results_keyboard(
            tournament_id=125,
            players=[player],
        )
    ) == ["Игрок", "⬅️ Назад", "❌ Отмена"]
    assert inline_keyboard_texts(
        superadmin_tournament_close_kb.admin_repair_add_existing_confirmation_keyboard(
            tournament_id=125,
            player_id=42,
        )
    ) == ["✅ Добавить", "⬅️ Назад", "❌ Отмена"]
    assert inline_keyboard_texts(
        superadmin_tournament_close_kb.admin_repair_add_new_confirmation_keyboard(
            tournament_id=125,
        )
    ) == ["✅ Создать", "⬅️ Назад", "❌ Отмена"]


def test_admin_close_tournament_nested_keyboards_show_back() -> None:
    keyboards = [
        superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
            tournament_id=125,
            page=0,
        ),
        superadmin_tournament_close_kb.admin_close_tournament_fund_error_keyboard(
            tournament_id=125,
            page=0,
        ),
        superadmin_tournament_close_kb.admin_close_tournament_confirmation_keyboard(
            tournament_id=125,
            page=0,
        ),
    ]

    for keyboard in keyboards:
        assert "⬅️ Назад" in inline_keyboard_texts(keyboard)
        assert "❌ Отмена" in inline_keyboard_texts(keyboard)


def test_close_tournament_tables_hide_disabled_columns_for_classic() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=[
            TournamentResultPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=1,
                knockouts_count=3,
                big_knockouts_count=1,
                tournament_points=Decimal("900"),
            )
        ],
        knockout_mode="none",
        supports_bonus_points=False,
    )

    card = result_fmt.close_tournament_card(results)
    closed = result_fmt.closed_tournament(results)

    assert first_code_block_lines(card)[0] == "№ Игрок"
    assert "КО" not in card
    assert "БКО" not in card
    assert "Бонус" not in card
    closed_header = closed.split("```")[1].splitlines()[1]
    assert "№" in closed_header
    assert "Игрок" in closed_header
    assert "Очки" in closed_header
    assert "КО" not in closed
    assert "БКО" not in closed
    assert "Бонус" not in closed


def test_admin_result_player_field_and_value_keyboards() -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 6, "Boss Bounty")
    player = TournamentResultPlayerView(
        player_id=108,
        display_name="Илларионов Александр",
        place=None,
        knockouts_count=0,
        big_knockouts_count=0,
    )
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=[player],
        knockout_mode="small_big",
    )

    field_buttons = [
        button.text
        for row in admin_results_kb.admin_result_player_fields_keyboard(
            results,
            player,
            page=0,
        ).inline_keyboard
        for button in row
    ]
    assert field_buttons == [
        "🥊 КО",
        "👑🥊 Босс КО",
        "🏁 Место",
        "❌ Отмена",
    ]
    assert (
        admin_result_handlers.result_field_name(admin_results_kb.AdminResultField.BIG_KNOCKOUTS)
        == "Босс КО"
    )
    assert result_fmt.field_prompt(player, "Босс КО") == "Илларионов Александр\n\nВыбери Босс КО:"
    assert admin_result_text.ADMIN_RESULTS_MANUAL_VALUE_PROMPTS["big"] == (
        "Введи количество Босс КО числом."
    )
    assert admin_result_text.ADMIN_RESULTS_INVALID_MANUAL_VALUE["big"] == (
        "Босс КО должно быть неотрицательным числом."
    )

    value_rows = admin_results_kb.admin_result_value_keyboard(
        tournament_id=125,
        page=0,
        player_id=108,
        field=admin_results_kb.AdminResultField.KNOCKOUTS,
    ).inline_keyboard
    assert [[button.text for button in row] for row in value_rows] == [
        ["1", "2", "3", "4", "5"],
        ["6", "7", "8", "9", "10"],
        ["11", "12", "13", "14", "15"],
        ["⌨️ Ввести руками"],
        ["⬅️ Назад"],
        ["❌ Отмена"],
    ]

    place_rows = admin_results_kb.admin_result_value_keyboard(
        tournament_id=125,
        page=0,
        player_id=108,
        field=admin_results_kb.AdminResultField.PLACE,
        occupied_places={2, 5},
    ).inline_keyboard
    assert [[button.text for button in row] for row in place_rows] == [
        ["1", "✔️ 2", "3", "4", "✔️ 5"],
        ["⬅️ Назад"],
        ["❌ Отмена"],
    ]


def test_tournament_label_fallback_is_unknown_tournament() -> None:
    known = tournament_view(125, date(2026, 7, 19), 2, "Weekly Deep Stack")
    unknown = tournament_view(126, date(2026, 7, 20), 999, None)

    assert tournament_fmt.label(known) == "Воскресенье, 19 июля — Weekly Deep Stack"
    assert tournament_fmt.label(unknown) == "Понедельник, 20 июля — Неопределённый турнир"


def test_check_in_summary_empty_tournament() -> None:
    view = SimpleNamespace(
        tournament=tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир"),
        registered_count=0,
        registered_checked_in_count=0,
        walk_in_count=0,
        checked_in_count=0,
    )

    assert check_in_fmt.summary(view) == (
        "✅ Чек-ин на турнир\n"
        "Воскресенье, 9 августа — Баунти турнир\n\n"
        "Зарегистрировано: 0\n"
        "Из них пришло: 0\n\n"
        "Пришло без регистрации: 0\n\n"
        "Всего в турнире: 0\n\n"
        "Выбери тип игрока:"
    )


def test_check_in_summary_mixed_sources() -> None:
    view = SimpleNamespace(
        tournament=tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир"),
        registered_count=3,
        registered_checked_in_count=2,
        walk_in_count=1,
        checked_in_count=3,
    )

    rendered = check_in_fmt.summary(view)

    assert "Зарегистрировано: 3" in rendered
    assert "Из них пришло: 2" in rendered
    assert "Пришло без регистрации: 1" in rendered
    assert "Всего в турнире: 3" in rendered
    assert "Ещё не отмечены" not in rendered


def test_checked_in_players_empty_state() -> None:
    view = SimpleNamespace(players=[], total_count=0)

    assert check_in_fmt.checked_in_players(view) == (
        "✅ Уже отметились\n\nПока никто не прошёл check-in.\n\nВсего: 0"
    )


def test_checked_in_players_list_hides_internal_ids() -> None:
    view = SimpleNamespace(
        players=[
            SimpleNamespace(player_id=101, telegram_id=1001, display_name="Иван"),
            SimpleNamespace(player_id=102, telegram_id=None, display_name="Пётр"),
        ],
        total_count=2,
    )

    rendered = check_in_fmt.checked_in_players(view)

    assert rendered == "✅ Уже отметились\n\n1. Иван\n2. Пётр\n\nВсего: 2"
    assert "101" not in rendered
    assert "1001" not in rendered


def test_check_in_success_message_is_shared_and_hides_internal_ids() -> None:
    tournament = tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир")
    user = SimpleNamespace(
        id=108,
        telegram_id=1001,
        display_name="Черепаха",
    )

    rendered = check_in_fmt.admin_success(tournament, user)

    assert rendered == (
        "✅ Игрок добавлен в турнир\n\nЧерепаха\nВоскресенье, 9 августа — Баунти турнир"
    )
    assert "108" not in rendered
    assert "1001" not in rendered


def test_check_in_main_keyboard_labels_and_checked_in_count() -> None:
    view = SimpleNamespace(
        tournament=tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир"),
        checked_in_count=16,
    )

    keyboard = admin_check_in_kb.admin_check_in_keyboard(view)

    assert inline_keyboard_texts(keyboard) == [
        "✅ Зарегистрированный",
        "👤 Играл ранее",
        "🆕 Новый игрок",
        "👥 Уже отметились (16)",
        "❌ Отмена",
    ]
    checked_in_callback = admin_check_in_kb.AdminCheckInCallback.unpack(
        keyboard.inline_keyboard[3][0].callback_data or ""
    )
    assert checked_in_callback.action == admin_check_in_kb.AdminCheckInAction.SHOW_CHECKED_IN


def test_check_in_main_keyboard_shows_zero_checked_in_count() -> None:
    view = SimpleNamespace(
        tournament=tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир"),
        checked_in_count=0,
    )

    keyboard = admin_check_in_kb.admin_check_in_keyboard(view)

    assert "👥 Уже отметились (0)" in inline_keyboard_texts(keyboard)


def test_check_in_input_prompt_keyboard_has_back_to_main() -> None:
    keyboard = admin_check_in_kb.admin_check_in_cancel_keyboard(tournament_id=125)

    assert inline_keyboard_texts(keyboard) == ["⬅️ Назад", "❌ Отмена"]
    back_callback = admin_check_in_kb.AdminCheckInCallback.unpack(
        keyboard.inline_keyboard[0][0].callback_data or ""
    )
    assert back_callback.action == admin_check_in_kb.AdminCheckInAction.BACK_TO_TOURNAMENT


def test_check_in_registered_search_results_back_returns_to_input() -> None:
    keyboard = admin_check_in_kb.admin_check_in_search_results_keyboard(
        tournament_id=125,
        players=[],
        action=admin_check_in_kb.AdminCheckInAction.CONFIRM_REGISTERED,
        back_action=admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH,
    )

    assert inline_keyboard_texts(keyboard) == ["↩️ Назад", "❌ Отмена"]
    back_callback = admin_check_in_kb.AdminCheckInCallback.unpack(
        keyboard.inline_keyboard[0][0].callback_data or ""
    )
    assert back_callback.action == admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH


def test_check_in_existing_search_results_back_returns_to_input() -> None:
    keyboard = admin_check_in_kb.admin_check_in_search_results_keyboard(
        tournament_id=125,
        players=[],
        action=admin_check_in_kb.AdminCheckInAction.CONFIRM_EXISTING,
        back_action=admin_check_in_kb.AdminCheckInAction.DATABASE_SEARCH,
    )

    back_callback = admin_check_in_kb.AdminCheckInCallback.unpack(
        keyboard.inline_keyboard[0][0].callback_data or ""
    )
    assert back_callback.action == admin_check_in_kb.AdminCheckInAction.DATABASE_SEARCH


def test_check_in_empty_search_back_returns_to_input() -> None:
    keyboard = admin_check_in_kb.admin_check_in_empty_search_keyboard(
        tournament_id=125,
        search_action=admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH,
    )

    assert inline_keyboard_texts(keyboard) == ["🔍 Искать снова", "↩️ Назад", "❌ Отмена"]
    back_callback = admin_check_in_kb.AdminCheckInCallback.unpack(
        keyboard.inline_keyboard[1][0].callback_data or ""
    )
    assert back_callback.action == admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH


async def test_place_only_result_player_opens_place_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 7, 19), 2, "Классика")
    target_player = TournamentResultPlayerView(
        player_id=108,
        display_name="Илларионов Александр",
        place=None,
        knockouts_count=0,
        big_knockouts_count=0,
    )
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=1800,
        players=[
            target_player,
            TournamentResultPlayerView(
                player_id=252,
                display_name="Тест Игрок",
                place=2,
                knockouts_count=0,
                big_knockouts_count=0,
            ),
        ],
        knockout_mode="none",
    )
    service = SimpleNamespace(get_tournament_results=AsyncMock(return_value=results))
    monkeypatch.setattr(admin_result_handlers, "result_service", service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock(), edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())

    await admin_result_handlers.select_result_player(
        callback,
        admin_results_kb.AdminResultPlayerCallback(
            action=admin_results_kb.AdminResultPlayerAction.OPEN,
            tournament_id=125,
            page=0,
            player_id=108,
        ),
        state,
    )

    state.clear.assert_awaited_once()
    callback.answer.assert_awaited_once()
    message.delete.assert_awaited_once()
    message.edit_text.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "\n".join(
        [
            "Игрок: Илларионов Александр",
            "",
            "Место: —",
        ]
    )
    assert [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ] == ["🏁 Место", "⬅️ Назад", "❌ Отмена"]


def admin_player(
    player_id: int,
    telegram_id: int,
    role: UserRole = UserRole.ADMIN,
) -> UserView:
    return UserView(
        id=player_id,
        telegram_id=telegram_id,
        display_name=f"Админ {player_id}",
        status=UserStatus.ACTIVE,
        role=role,
    )


def tournament_view(
    tournament_id: int,
    tournament_date: date,
    tournament_type_id: int,
    tournament_type_name: str | None = None,
    tournament_type_code: str | None = None,
) -> TournamentView:
    return TournamentView(
        id=tournament_id,
        date=tournament_date,
        tournament_type_id=tournament_type_id,
        tournament_type_name=tournament_type_name,
        tournament_type_code=tournament_type_code,
    )


def keyboard_texts(reply_markup: object) -> list[str]:
    return [button.text for row in reply_markup.keyboard for button in row]


def keyboard_rows(reply_markup: object) -> list[list[str]]:
    return [[button.text for button in row] for row in reply_markup.keyboard]


def inline_keyboard_texts(reply_markup: object) -> list[str]:
    return [button.text for row in reply_markup.inline_keyboard for button in row]


class MutableState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.state: object | None = None
        self.clear = AsyncMock(side_effect=self._clear)
        self.set_state = AsyncMock(side_effect=self._set_state)
        self.update_data = AsyncMock(side_effect=self._update_data)
        self.get_data = AsyncMock(side_effect=self._get_data)

    async def _clear(self) -> None:
        self.data.clear()
        self.state = None

    async def _set_state(self, state: object) -> None:
        self.state = state

    async def _update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def _get_data(self) -> dict[str, object]:
        return dict(self.data)


def registration_candidate(player_id: int, score: int) -> RegistrationCandidateView:
    return RegistrationCandidateView(
        user=UserView(
            id=player_id,
            telegram_id=None,
            display_name=f"Исторический {player_id}",
            status=UserStatus.ACTIVE,
            role=UserRole.PLAYER,
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


def registrations_overview(
    *,
    pending_count: int = 0,
    tournament_count: int = 0,
) -> RegistrationsOverviewView:
    tournaments = []
    if tournament_count:
        tournaments.append(
            TournamentRegistrationCountView(
                tournament_id=1,
                date=date(2026, 8, 19),
                tournament_type_name="Баунти",
                registrations_count=tournament_count,
            )
        )
    return RegistrationsOverviewView(
        pending_user_registration_count=pending_count,
        active_tournament_registration_count=tournament_count,
        tournaments=tournaments,
    )


async def test_admin_check_in_registered_user_flow_creates_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'telegram_check_in.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Админ Первый",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        registered_user = build_player(
            telegram_id=101,
            display_name="Игрок Админ",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        session.add_all([season, admin, registered_user])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(
            TournamentRegistration(
                tournament_id=tournament.id,
                player_id=registered_user.id,
            )
        )
        await session.commit()
        tournament_id = tournament.id
        registered_user_id = registered_user.id

    service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    try:
        open_message = SimpleNamespace(
            from_user=SimpleNamespace(id=100),
            answer=AsyncMock(),
        )

        await admin_check_in_handlers.show_admin_check_in(open_message)

        opened_text = open_message.answer.await_args.args[0]
        assert "Зарегистрировано: 1" in opened_text
        assert "Из них пришло: 0" in opened_text
        assert "Пришло без регистрации: 0" in opened_text
        assert "Всего в турнире: 0" in opened_text

        state = MutableState()
        search_prompt_message = SimpleNamespace(
            delete=AsyncMock(),
            answer=AsyncMock(return_value=SimpleNamespace(message_id=77)),
        )
        search_prompt_callback = SimpleNamespace(
            from_user=SimpleNamespace(id=100),
            message=search_prompt_message,
            answer=AsyncMock(),
        )
        await admin_check_in_handlers.select_check_in_action(
            search_prompt_callback,
            admin_check_in_kb.AdminCheckInCallback(
                action=admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH,
                tournament_id=tournament_id,
            ),
            state,
        )

        search_message = SimpleNamespace(
            from_user=SimpleNamespace(id=100),
            text="Игрок",
            chat=SimpleNamespace(id=100),
            bot=SimpleNamespace(edit_message_reply_markup=AsyncMock()),
            answer=AsyncMock(),
        )
        await admin_check_in_handlers.enter_registered_check_in_search(search_message, state)

        search_message.bot.edit_message_reply_markup.assert_awaited_once_with(
            chat_id=100,
            message_id=77,
            reply_markup=None,
        )
        search_answer = search_message.answer.await_args
        assert search_answer.args[0] == "Нашел среди зарегистрированных:"
        assert inline_keyboard_texts(search_answer.kwargs["reply_markup"])[:1] == ["Игрок Админ"]

        confirmation_message = SimpleNamespace(edit_text=AsyncMock())
        confirmation_callback = SimpleNamespace(
            from_user=SimpleNamespace(id=100),
            message=confirmation_message,
            answer=AsyncMock(),
        )
        await admin_check_in_handlers.select_check_in_action(
            confirmation_callback,
            admin_check_in_kb.AdminCheckInCallback(
                action=admin_check_in_kb.AdminCheckInAction.CONFIRM_REGISTERED,
                tournament_id=tournament_id,
                player_id=registered_user_id,
            ),
            state,
        )

        confirmation_message.edit_text.assert_awaited_once()
        assert (
            "Добавить Игрок Админ в сегодняшний турнир?"
            in (confirmation_message.edit_text.await_args.args[0])
        )
        assert inline_keyboard_texts(
            confirmation_message.edit_text.await_args.kwargs["reply_markup"]
        ) == ["✅ Подтвердить", "↩️ Назад", "❌ Отмена"]

        final_message = SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock())
        final_callback = SimpleNamespace(
            from_user=SimpleNamespace(id=100),
            message=final_message,
            answer=AsyncMock(),
            bot=SimpleNamespace(send_message=AsyncMock()),
        )
        await admin_check_in_handlers.select_check_in_action(
            final_callback,
            admin_check_in_kb.AdminCheckInCallback(
                action=admin_check_in_kb.AdminCheckInAction.ADD_REGISTERED,
                tournament_id=tournament_id,
                player_id=registered_user_id,
            ),
            state,
        )

        final_callback.answer.assert_awaited_once_with("Результат сохранен.")
        final_message.edit_text.assert_awaited_once()
        assert "✅ Игрок добавлен в турнир" in final_message.edit_text.await_args.args[0]
        assert "Игрок Админ" in final_message.edit_text.await_args.args[0]
        final_message.answer.assert_awaited_once()
        assert "Из них пришло: 1" in final_message.answer.await_args.args[0]
        assert "Всего в турнире: 1" in final_message.answer.await_args.args[0]
        async with session_factory() as session:
            results = list((await session.execute(select(TournamentResult))).scalars())
        assert len(results) == 1
        assert results[0].tournament_id == tournament_id
        assert results[0].player_id == registered_user_id
        assert results[0].source == TournamentResultSource.REGISTERED
    finally:
        await engine.dispose()


async def test_check_in_database_search_clears_prompt_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(search_users=AsyncMock(return_value=[]))
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    state = MutableState()
    await state.set_state(AdminResultStates.entering_database_check_in_search)
    await state.update_data(check_in_tournament_id=125, check_in_prompt_message_id=77)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="Черепаха",
        chat=SimpleNamespace(id=100),
        bot=SimpleNamespace(edit_message_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )

    await admin_check_in_handlers.enter_database_check_in_search(message, state)

    message.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=100,
        message_id=77,
        reply_markup=None,
    )
    service.search_users.assert_awaited_once_with(
        admin_telegram_id=100,
        tournament_id=125,
        query="Черепаха",
    )


async def test_check_in_new_player_clears_prompt_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир")
    service = SimpleNamespace(
        find_new_player_candidates=AsyncMock(return_value=("черепаха", [], False)),
        get_new_user_check_in_confirmation=AsyncMock(return_value=(tournament, "Черепаха")),
    )
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    state = MutableState()
    await state.set_state(AdminResultStates.entering_new_check_in_player)
    await state.update_data(check_in_tournament_id=125, check_in_prompt_message_id=77)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="Черепаха",
        chat=SimpleNamespace(id=100),
        bot=SimpleNamespace(edit_message_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )

    await admin_check_in_handlers.enter_new_check_in_player(message, state)

    message.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=100,
        message_id=77,
        reply_markup=None,
    )
    assert state.state == AdminResultStates.confirming_new_check_in_player
    assert message.answer.await_args.args[0] == check_in_fmt.new_confirmation(
        tournament,
        "Черепаха",
    )


async def test_check_in_input_back_returns_to_main_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = SimpleNamespace(
        tournament=tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир"),
        registered_count=1,
        registered_checked_in_count=0,
        walk_in_count=0,
        checked_in_count=0,
    )
    service = SimpleNamespace(get_check_in=AsyncMock(return_value=view))
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_check_in_handlers.select_check_in_action(
        callback,
        admin_check_in_kb.AdminCheckInCallback(
            action=admin_check_in_kb.AdminCheckInAction.BACK_TO_TOURNAMENT,
            tournament_id=125,
        ),
        state,
    )

    state.clear.assert_awaited_once()
    service.get_check_in.assert_awaited_once_with(admin_telegram_id=100, tournament_id=125)
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0].startswith("✅ Чек-ин на турнир")


async def test_check_in_search_results_back_returns_to_registered_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace()
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    state = MutableState()
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_check_in_handlers.select_check_in_action(
        callback,
        admin_check_in_kb.AdminCheckInCallback(
            action=admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH,
            tournament_id=125,
        ),
        state,
    )

    state.set_state.assert_awaited_once_with(AdminResultStates.entering_registered_check_in_search)
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "Введи имя зарегистрированного игрока."
    assert inline_keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == [
        "⬅️ Назад",
        "❌ Отмена",
    ]


async def test_checked_in_players_screen_opens_from_check_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_in_view = SimpleNamespace(
        players=[
            SimpleNamespace(display_name="Иван"),
            SimpleNamespace(display_name="Пётр"),
        ],
        total_count=2,
    )
    service = SimpleNamespace(get_checked_in_players=AsyncMock(return_value=checked_in_view))
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    state = SimpleNamespace()
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_check_in_handlers.select_check_in_action(
        callback,
        admin_check_in_kb.AdminCheckInCallback(
            action=admin_check_in_kb.AdminCheckInAction.SHOW_CHECKED_IN,
            tournament_id=125,
        ),
        state,
    )

    service.get_checked_in_players.assert_awaited_once_with(
        admin_telegram_id=100,
        tournament_id=125,
    )
    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()
    assert (
        message.edit_text.await_args.args[0] == "✅ Уже отметились\n\n1. Иван\n2. Пётр\n\nВсего: 2"
    )
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "⬅️ Назад",
        "❌ Отмена",
    ]


async def test_checked_in_players_back_refreshes_main_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = SimpleNamespace(
        tournament=tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир"),
        registered_count=3,
        registered_checked_in_count=2,
        walk_in_count=1,
        checked_in_count=3,
    )
    service = SimpleNamespace(get_check_in=AsyncMock(return_value=view))
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_check_in_handlers.select_check_in_action(
        callback,
        admin_check_in_kb.AdminCheckInCallback(
            action=admin_check_in_kb.AdminCheckInAction.BACK_TO_TOURNAMENT,
            tournament_id=125,
        ),
        state,
    )

    service.get_check_in.assert_awaited_once_with(admin_telegram_id=100, tournament_id=125)
    message.edit_text.assert_awaited_once()
    assert "👥 Уже отметились (3)" in inline_keyboard_texts(
        message.edit_text.await_args.kwargs["reply_markup"]
    )


async def test_checked_in_players_dispatcher_open_and_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_in_view = SimpleNamespace(
        players=[SimpleNamespace(display_name="Иван")],
        total_count=1,
    )
    main_view = SimpleNamespace(
        tournament=tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир"),
        registered_count=1,
        registered_checked_in_count=1,
        walk_in_count=0,
        checked_in_count=1,
    )
    service = SimpleNamespace(
        get_checked_in_players=AsyncMock(return_value=checked_in_view),
        get_check_in=AsyncMock(return_value=main_view),
    )
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    bot = RecordingBot()

    def callback_update(update_id: int, data: str, text: str) -> dict[str, object]:
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"check-in-callback-{update_id}",
                "from": {"id": 100, "is_bot": False, "first_name": "Админ"},
                "message": {
                    "message_id": 10,
                    "date": 1783598400,
                    "chat": {"id": 100, "type": "private"},
                    "text": text,
                },
                "chat_instance": "chat-instance",
                "data": data,
            },
        }

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                1,
                admin_check_in_kb.AdminCheckInCallback(
                    action=admin_check_in_kb.AdminCheckInAction.SHOW_CHECKED_IN,
                    tournament_id=125,
                ).pack(),
                "✅ Чек-ин на турнир",
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                2,
                admin_check_in_kb.AdminCheckInCallback(
                    action=admin_check_in_kb.AdminCheckInAction.BACK_TO_TOURNAMENT,
                    tournament_id=125,
                ).pack(),
                "✅ Уже отметились",
            ),
        )

        edited_texts = [
            call.text for call in bot.calls if call.__class__.__name__ == "EditMessageText"
        ]
        assert edited_texts == [
            "✅ Уже отметились\n\n1. Иван\n\nВсего: 1",
            check_in_fmt.summary(main_view),
        ]
    finally:
        await bot.session.close()


async def test_admin_check_in_registered_user_dispatcher_flow_creates_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'telegram_check_in_dispatcher.db'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Админ Первый",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        player = build_player(
            telegram_id=101,
            display_name="Игрок Первый",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, admin, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(TournamentRegistration(tournament_id=tournament.id, player_id=player.id))
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    monkeypatch.setattr(admin_check_in_handlers, "tournament_check_in_service", service)
    bot = RecordingBot()

    def callback_update(update_id: int, data: str, message_id: int = 10) -> dict[str, object]:
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"callback-{update_id}",
                "from": {"id": 100, "is_bot": False, "first_name": "Админ"},
                "message": {
                    "message_id": message_id,
                    "date": 1783598400,
                    "chat": {"id": 100, "type": "private"},
                    "text": "check-in",
                },
                "chat_instance": "chat-instance",
                "data": data,
            },
        }

    def message_update(update_id: int, text: str) -> dict[str, object]:
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id + 100,
                "date": 1783598400,
                "chat": {"id": 100, "type": "private"},
                "from": {"id": 100, "is_bot": False, "first_name": "Админ"},
                "text": text,
            },
        }

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                1,
                admin_check_in_kb.AdminCheckInCallback(
                    action=admin_check_in_kb.AdminCheckInAction.REGISTERED_SEARCH,
                    tournament_id=tournament_id,
                ).pack(),
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(bot, message_update(2, "Игрок"))
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                3,
                admin_check_in_kb.AdminCheckInCallback(
                    action=admin_check_in_kb.AdminCheckInAction.CONFIRM_REGISTERED,
                    tournament_id=tournament_id,
                    player_id=player_id,
                ).pack(),
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                4,
                admin_check_in_kb.AdminCheckInCallback(
                    action=admin_check_in_kb.AdminCheckInAction.ADD_REGISTERED,
                    tournament_id=tournament_id,
                    player_id=player_id,
                ).pack(),
            ),
        )

        method_names = [call.__class__.__name__ for call in bot.calls]
        assert "EditMessageText" in method_names
        assert "EditMessageReplyMarkup" in method_names
        edited_texts = [
            call.text for call in bot.calls if call.__class__.__name__ == "EditMessageText"
        ]
        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        assert any("Добавить Игрок Первый в сегодняшний турнир?" in text for text in edited_texts)
        assert any("✅ Игрок добавлен в турнир" in text for text in edited_texts)
        assert any("Игрок Первый" in text for text in edited_texts)
        assert any("Четверг, 9 июля — Классика" in text for text in edited_texts)
        assert any("Из них пришло: 1" in text for text in sent_texts)
        assert any("Всего в турнире: 1" in text for text in sent_texts)
        async with session_factory() as session:
            results = list((await session.execute(select(TournamentResult))).scalars())
        assert len(results) == 1
        assert results[0].tournament_id == tournament_id
        assert results[0].player_id == player_id
        assert results[0].source == TournamentResultSource.REGISTERED
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_admin_result_dispatcher_flow_reassigns_occupied_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'telegram_results.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        admin = build_player(
            telegram_id=200,
            display_name="Админ Результатов",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        occupied_player = build_player(
            telegram_id=202,
            display_name="Игрок С Местом",
            status=UserStatus.ACTIVE,
        )
        player = build_player(
            telegram_id=201,
            display_name="Игрок Результатов",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, admin, occupied_player, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=occupied_player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=admin.id,
                    place=1,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=admin.id,
                ),
            ]
        )
        await session.commit()
        tournament_id = tournament.id
        occupied_player_id = occupied_player.id
        player_id = player.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    monkeypatch.setattr(admin_result_handlers, "result_service", service)
    bot = RecordingBot()

    def message_update(update_id: int, text: str) -> dict[str, object]:
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id + 100,
                "date": 1783598400,
                "chat": {"id": 200, "type": "private"},
                "from": {"id": 200, "is_bot": False, "first_name": "Админ"},
                "text": text,
            },
        }

    def callback_update(update_id: int, data: str, message_id: int = 300) -> dict[str, object]:
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"result-callback-{update_id}",
                "from": {"id": 200, "is_bot": False, "first_name": "Админ"},
                "message": {
                    "message_id": message_id,
                    "date": 1783598400,
                    "chat": {"id": 200, "type": "private"},
                    "text": "results",
                },
                "chat_instance": "chat-instance",
                "data": data,
            },
        }

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            message_update(1, labels.ADMIN_PANEL_RESULTS),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                2,
                admin_results_kb.AdminResultMenuCallback(
                    action=admin_results_kb.AdminResultMenuAction.DATA,
                    tournament_id=tournament_id,
                ).pack(),
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                3,
                admin_results_kb.AdminResultPlayerCallback(
                    action=admin_results_kb.AdminResultPlayerAction.OPEN,
                    tournament_id=tournament_id,
                    page=0,
                    player_id=player_id,
                ).pack(),
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                4,
                admin_results_kb.AdminResultValueCallback(
                    action=admin_results_kb.AdminResultValueAction.SET,
                    tournament_id=tournament_id,
                    page=0,
                    player_id=player_id,
                    field=admin_results_kb.AdminResultField.PLACE,
                    value=1,
                ).pack(),
            ),
        )

        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        edited_texts = [
            call.text for call in bot.calls if call.__class__.__name__ == "EditMessageText"
        ]
        assert sent_texts
        assert "🏁 Внести результаты" in sent_texts[0]
        assert "Четверг, 9 июля — Классика" in sent_texts[0]
        assert "Выбери турнир для внесения " + "результатов" not in sent_texts[0]
        assert "В " + "работе" not in sent_texts[0]
        all_rendered_texts = [*sent_texts, *edited_texts]
        assert any("Игроки турнира" in text for text in all_rendered_texts)
        assert any("Игрок: Игрок Результатов\n\nМесто: —" in text for text in all_rendered_texts)
        assert any("Игрок: Игрок Результатов\n\nМесто: 1" in text for text in all_rendered_texts)
        async with session_factory() as session:
            reassigned = (
                await session.execute(
                    select(TournamentResult).where(
                        TournamentResult.tournament_id == tournament_id,
                        TournamentResult.player_id == player_id,
                    )
                )
            ).scalar_one()
            old_place = (
                await session.execute(
                    select(TournamentResult).where(
                        TournamentResult.tournament_id == tournament_id,
                        TournamentResult.player_id == occupied_player_id,
                    )
                )
            ).scalar_one()
        assert reassigned.place == 1
        assert old_place.place is None
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_superadmin_close_tournament_dispatcher_replaces_fund_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'telegram_close.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        superadmin = build_player(
            telegram_id=300,
            display_name="Суперадмин Закрытия",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        players = [
            build_player(
                telegram_id=301 + index,
                display_name=f"Игрок Закрытия {index + 1}",
                status=UserStatus.ACTIVE,
            )
            for index in range(5)
        ]
        session.add_all([season, superadmin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=superadmin.id,
                    place=index + 1,
                )
                for index, player in enumerate(players)
            ]
        )
        session.add(
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="close-file-1",
                telegram_file_unique_id="close-unique-1",
                uploaded_by_user_id=superadmin.id,
                position=0,
            )
        )
        await session.commit()
        tournament_id = tournament.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    monkeypatch.setattr(
        superadmin_close_handlers.tournament_planning_service,
        "inspect_after_tournament_close",
        AsyncMock(return_value=SimpleNamespace(status=SimpleNamespace(), plan=None)),
    )
    bot = RecordingBot()

    def message_update(update_id: int, text: str) -> dict[str, object]:
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id + 100,
                "date": 1783598400,
                "chat": {"id": 300, "type": "private"},
                "from": {"id": 300, "is_bot": False, "first_name": "Суперадмин"},
                "text": text,
            },
        }

    def callback_update(update_id: int, data: str, message_id: int = 500) -> dict[str, object]:
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"close-callback-{update_id}",
                "from": {"id": 300, "is_bot": False, "first_name": "Суперадмин"},
                "message": {
                    "message_id": message_id,
                    "date": 1783598400,
                    "chat": {"id": 300, "type": "private"},
                    "text": "Подтвердите закрытие турнира.",
                },
                "chat_instance": "chat-instance",
                "data": data,
            },
        }

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            message_update(1, labels.ADMIN_PANEL_CLOSE_TOURNAMENT),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                2,
                superadmin_tournament_close_kb.AdminCloseTournamentCallback(
                    action=superadmin_tournament_close_kb.AdminCloseTournamentAction.OPEN,
                    tournament_id=tournament_id,
                    page=0,
                ).pack(),
                message_id=101,
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(bot, message_update(3, "10000"))
        async with session_factory() as session:
            tournament_before_change = await session.get(Tournament, tournament_id)
            assert tournament_before_change is not None
            assert tournament_before_change.status == TournamentStatus.ACTIVE
            assert tournament_before_change.tournament_fund is None

        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                4,
                superadmin_tournament_close_kb.AdminCloseTournamentCallback(
                    action=superadmin_tournament_close_kb.AdminCloseTournamentAction.CHANGE_FUND,
                    tournament_id=tournament_id,
                    page=0,
                ).pack(),
            ),
        )
        async with session_factory() as session:
            tournament_after_change = await session.get(Tournament, tournament_id)
            assert tournament_after_change is not None
            assert tournament_after_change.status == TournamentStatus.ACTIVE
            assert tournament_after_change.tournament_fund is None

        await runtime.telegram_dispatcher.feed_raw_update(bot, message_update(5, "15000"))
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                6,
                superadmin_tournament_close_kb.AdminCloseTournamentCallback(
                    action=superadmin_tournament_close_kb.AdminCloseTournamentAction.CONFIRM,
                    tournament_id=tournament_id,
                    page=0,
                ).pack(),
            ),
        )

        method_names = [call.__class__.__name__ for call in bot.calls]
        assert method_names.count("DeleteMessage") >= 2
        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        edited_texts = [
            call.text for call in bot.calls if call.__class__.__name__ == "EditMessageText"
        ]
        assert "🔒 Закрыть турнир" in sent_texts[0]
        assert any("🔒 Закрытие турнира" in text for text in edited_texts)
        assert any("Введите фонд турнира?" in text for text in edited_texts)
        assert "Введите фонд турнира." in edited_texts
        assert any("Фонд турнира: 10000" in text for text in sent_texts)
        assert any("Фонд турнира: 15000" in text for text in sent_texts)
        assert any("✅ Турнир закрыт" in text for text in sent_texts)

        async with session_factory() as session:
            closed_tournament = await session.get(Tournament, tournament_id)
            assert closed_tournament is not None
            assert closed_tournament.status == TournamentStatus.CLOSED
            assert closed_tournament.tournament_fund == 15000
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_future_tournament_close_callback_shows_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_closeable_tournament_results=AsyncMock(side_effect=FutureTournamentCannotBeClosedError)
    )
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )
    state = MutableState()

    await superadmin_close_handlers.select_close_tournament_action(
        callback,
        superadmin_tournament_close_kb.AdminCloseTournamentCallback(
            action=superadmin_tournament_close_kb.AdminCloseTournamentAction.OPEN,
            tournament_id=7,
            page=0,
        ),
        state,
    )

    assert callback.answer.await_args_list[-1].args == ("Будущий турнир нельзя закрыть.",)
    assert callback.answer.await_args_list[-1].kwargs == {"show_alert": True}
    callback.message.edit_text.assert_not_awaited()


async def test_close_tournament_single_ready_tournament_root_shows_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=None,
        players=[
            TournamentResultPlayerView(
                player_id=1,
                display_name="Игрок",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
            )
        ],
        photo_count=1,
    )
    readiness = TournamentCloseReadinessView(
        tournament=tournament,
        is_ready=True,
        photo_count=1,
        has_photos=True,
        has_checkins=True,
        validation_errors=[],
        reasons=[],
    )
    service = SimpleNamespace(
        list_unclosed_tournaments_for_superadmin=AsyncMock(return_value=[readiness]),
        get_closeable_tournament_results=AsyncMock(return_value=results),
        get_close_readiness=AsyncMock(return_value=readiness),
    )
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    state = MutableState()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )
    sent_message = SimpleNamespace(chat=SimpleNamespace(id=100), message_id=700)
    message.answer.return_value = sent_message

    await superadmin_close_handlers.show_close_tournament_flow(message, state)

    service.list_unclosed_tournaments_for_superadmin.assert_awaited_once_with(100)
    service.get_closeable_tournament_results.assert_not_awaited()
    service.get_close_readiness.assert_not_awaited()
    assert state.state is None
    message.answer.assert_awaited_once()
    assert "🔒 Закрыть турнир" in message.answer.await_args.args[0]
    assert "Баунти турнир" in message.answer.await_args.args[0]
    assert inline_keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == [
        "✅ 09.08 — Баунти турнир",
        "🛠 Корректировать турниры",
        "❌ Отмена",
    ]


async def test_close_tournament_fund_back_returns_to_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир")
    readiness = TournamentCloseReadinessView(
        tournament=tournament,
        is_ready=True,
        photo_count=1,
        has_photos=True,
        has_checkins=True,
        validation_errors=[],
        reasons=[],
    )
    service = SimpleNamespace(
        list_unclosed_tournaments_for_superadmin=AsyncMock(return_value=[readiness])
    )
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    state = MutableState()
    await state.set_state(AdminResultStates.entering_tournament_fund)
    await state.update_data(close_tournament_id=125, close_tournament_page=0)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await superadmin_close_handlers.select_close_tournament_action(
        callback,
        superadmin_tournament_close_kb.AdminCloseTournamentCallback(
            action=superadmin_tournament_close_kb.AdminCloseTournamentAction.BACK,
            tournament_id=125,
            page=0,
        ),
        state,
    )

    service.list_unclosed_tournaments_for_superadmin.assert_awaited_once_with(100)
    callback.answer.assert_awaited_once_with()
    assert state.state is None
    assert "🔒 Закрыть турнир" in message.edit_text.await_args.args[0]
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "✅ 09.08 — Баунти турнир",
        "🛠 Корректировать турниры",
        "❌ Отмена",
    ]


async def test_close_tournament_confirmation_back_returns_to_fund_input() -> None:
    state = MutableState()
    await state.update_data(
        close_tournament_id=125,
        close_tournament_page=0,
        tournament_fund=15000,
    )
    message = SimpleNamespace(
        chat=SimpleNamespace(id=100),
        message_id=700,
        edit_text=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await superadmin_close_handlers.select_close_tournament_action(
        callback,
        superadmin_tournament_close_kb.AdminCloseTournamentCallback(
            action=superadmin_tournament_close_kb.AdminCloseTournamentAction.BACK,
            tournament_id=125,
            page=0,
        ),
        state,
    )

    callback.answer.assert_awaited_once_with()
    assert state.state == AdminResultStates.entering_tournament_fund
    assert state.data["tournament_fund"] == 15000
    assert state.data["close_tournament_prompt_message_id"] == 700
    assert message.edit_text.await_args.args[0] == "Введите фонд турнира."
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "⬅️ Назад",
        "❌ Отмена",
    ]


async def test_correction_list_back_returns_to_close_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир")
    readiness = TournamentCloseReadinessView(
        tournament=tournament,
        is_ready=True,
        photo_count=1,
        has_photos=True,
        has_checkins=True,
        validation_errors=[],
        reasons=[],
    )
    service = SimpleNamespace(
        list_unclosed_tournaments_for_superadmin=AsyncMock(return_value=[readiness])
    )
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    state = MutableState()
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await superadmin_close_handlers.select_close_tournament_action(
        callback,
        superadmin_tournament_close_kb.AdminCloseTournamentCallback(
            action=superadmin_tournament_close_kb.AdminCloseTournamentAction.BACK,
            page=0,
        ),
        state,
    )

    assert "🔒 Закрыть турнир" in message.edit_text.await_args.args[0]
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "✅ 09.08 — Баунти турнир",
        "🛠 Корректировать турниры",
        "❌ Отмена",
    ]


async def test_correction_card_back_returns_to_correction_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир")
    readiness = TournamentCloseReadinessView(
        tournament=tournament,
        is_ready=True,
        photo_count=1,
        has_photos=True,
        has_checkins=True,
        validation_errors=[],
        reasons=[],
    )
    service = SimpleNamespace(
        list_unclosed_tournaments_for_superadmin=AsyncMock(return_value=[readiness])
    )
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    state = MutableState()
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await superadmin_close_handlers.select_close_tournament_action(
        callback,
        superadmin_tournament_close_kb.AdminCloseTournamentCallback(
            action=superadmin_tournament_close_kb.AdminCloseTournamentAction.CORRECTION_LIST,
            page=0,
        ),
        state,
    )

    assert "🛠 Корректировать турниры" in message.edit_text.await_args.args[0]
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "✅ 09.08 — Баунти турнир",
        "⬅️ Назад",
        "❌ Отмена",
    ]


async def test_close_tournament_change_fund_deletes_preview_and_waits_for_new_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(validate_closeable_results=AsyncMock(return_value=[]))
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    state = MutableState()
    await state.update_data(
        close_tournament_id=125,
        close_tournament_page=0,
        tournament_fund=10000,
    )
    message = SimpleNamespace(delete=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await superadmin_close_handlers.select_close_tournament_action(
        callback,
        superadmin_tournament_close_kb.AdminCloseTournamentCallback(
            action=superadmin_tournament_close_kb.AdminCloseTournamentAction.CHANGE_FUND,
            tournament_id=125,
            page=0,
        ),
        state,
    )

    service.validate_closeable_results.assert_awaited_once_with(
        superadmin_telegram_id=100,
        tournament_id=125,
    )
    callback.answer.assert_awaited_once_with()
    message.delete.assert_awaited_once_with()
    assert state.state == AdminResultStates.entering_tournament_fund
    assert state.data == {"close_tournament_id": 125, "close_tournament_page": 0}


async def test_close_tournament_invalid_fund_stays_in_input_flow() -> None:
    state = MutableState()
    await state.set_state(AdminResultStates.entering_tournament_fund)
    await state.update_data(close_tournament_id=125, close_tournament_page=0)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="101",
        answer=AsyncMock(),
    )

    await superadmin_close_handlers.enter_tournament_fund(message, state)

    assert state.state == AdminResultStates.entering_tournament_fund
    assert state.data == {"close_tournament_id": 125, "close_tournament_page": 0}
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == (
        "Фонд турнира должен быть положительным целым числом, кратным 10.\n\nВведите фонд турнира."
    )
    assert "Закрытие турнира" not in message.answer.await_args.args[0]


async def test_close_tournament_valid_fund_replaces_root_preview_with_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournament_view(125, date(2026, 8, 9), 1, "Баунти турнир")
    results = TournamentResultsView(
        tournament=tournament,
        tournament_fund=None,
        players=[
            TournamentResultPlayerView(
                player_id=108,
                display_name="Илларионов Александр",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
            )
        ],
        knockout_mode="none",
    )
    service = SimpleNamespace(get_closeable_tournament_results=AsyncMock(return_value=results))
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    state = MutableState()
    await state.set_state(AdminResultStates.entering_tournament_fund)
    await state.update_data(
        close_tournament_id=125,
        close_tournament_page=0,
        close_tournament_prompt_chat_id=100,
        close_tournament_prompt_message_id=700,
    )
    bot = SimpleNamespace(edit_message_text=AsyncMock())
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="15000",
        bot=bot,
        answer=AsyncMock(),
    )

    await superadmin_close_handlers.enter_tournament_fund(message, state)

    service.get_closeable_tournament_results.assert_awaited_once_with(
        superadmin_telegram_id=100,
        tournament_id=125,
    )
    bot.edit_message_text.assert_awaited_once_with(
        chat_id=100,
        message_id=700,
        text="Введите фонд турнира.",
        reply_markup=superadmin_tournament_close_kb.admin_close_tournament_card_keyboard(
            tournament_id=125,
            page=0,
        ),
    )
    message.answer.assert_awaited_once()
    assert "Фонд турнира: 15000" in message.answer.await_args.args[0]
    assert state.state is None
    assert state.data["tournament_fund"] == 15000


async def test_admin_photo_collection_reissues_single_control_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, tournament_id = await _build_photo_collection_service(
        tmp_path / "admin_photo_collection.db",
        telegram_id=100,
        role=UserRole.ADMIN,
    )
    monkeypatch.setattr(admin_result_handlers, "result_service", service)
    bot = RecordingBot()

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_callback_update(
                1,
                user_id=100,
                data=admin_results_kb.AdminResultPlayerCallback(
                    action=admin_results_kb.AdminResultPlayerAction.ADD_PHOTO,
                    tournament_id=tournament_id,
                    page=0,
                    player_id=0,
                ).pack(),
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_message_update(2, user_id=100, file_id="file-1", unique_id="unique-1"),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_message_update(3, user_id=100, file_id="file-2", unique_id="unique-2"),
        )

        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        method_names = [call.__class__.__name__ for call in bot.calls]
        assert "Загружено фото: 0" in sent_texts[0]
        assert "Загружено фото: 1" in sent_texts[1]
        assert "Загружено фото: 2" in sent_texts[2]
        assert all("Фото добавлено" not in text for text in sent_texts)
        assert method_names.count("DeleteMessage") >= 3
        async with service.session_factory() as session:
            photos = await TournamentPhotoRepository(session).list_for_tournament(tournament_id)
        assert len(photos) == 2
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_admin_photo_collection_album_refreshes_control_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, tournament_id = await _build_photo_collection_service(
        tmp_path / "admin_photo_album.db",
        telegram_id=100,
        role=UserRole.ADMIN,
    )
    monkeypatch.setattr(admin_result_handlers, "result_service", service)
    bot = RecordingBot()

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_callback_update(
                10,
                user_id=100,
                data=admin_results_kb.AdminResultPlayerCallback(
                    action=admin_results_kb.AdminResultPlayerAction.ADD_PHOTO,
                    tournament_id=tournament_id,
                    page=0,
                    player_id=0,
                ).pack(),
            ),
        )
        await asyncio.gather(
            runtime.telegram_dispatcher.feed_raw_update(
                bot,
                _photo_message_update(
                    11,
                    user_id=100,
                    file_id="album-file-1",
                    unique_id="album-unique-1",
                    media_group_id="album-1",
                ),
            ),
            runtime.telegram_dispatcher.feed_raw_update(
                bot,
                _photo_message_update(
                    12,
                    user_id=100,
                    file_id="album-file-2",
                    unique_id="album-unique-2",
                    media_group_id="album-1",
                ),
            ),
            runtime.telegram_dispatcher.feed_raw_update(
                bot,
                _photo_message_update(
                    13,
                    user_id=100,
                    file_id="album-file-3",
                    unique_id="album-unique-3",
                    media_group_id="album-1",
                ),
            ),
        )
        await asyncio.sleep(0.5)

        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        control_texts = [text for text in sent_texts if "📸 Добавление фото" in text]
        assert len(control_texts) == 2
        assert "Загружено фото: 0" in control_texts[0]
        assert "Загружено фото: 3" in control_texts[1]
        assert all("Фото добавлено" not in text for text in sent_texts)
        async with service.session_factory() as session:
            photos = await TournamentPhotoRepository(session).list_for_tournament(tournament_id)
        assert len(photos) == 3
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_admin_photo_collection_duplicate_and_limit_use_control_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, tournament_id = await _build_photo_collection_service(
        tmp_path / "admin_photo_limit.db",
        telegram_id=100,
        role=UserRole.ADMIN,
    )
    monkeypatch.setattr(admin_result_handlers, "result_service", service)
    bot = RecordingBot()

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_callback_update(
                20,
                user_id=100,
                data=admin_results_kb.AdminResultPlayerCallback(
                    action=admin_results_kb.AdminResultPlayerAction.ADD_PHOTO,
                    tournament_id=tournament_id,
                    page=0,
                    player_id=0,
                ).pack(),
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_message_update(21, user_id=100, file_id="file-1", unique_id="unique-1"),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_message_update(22, user_id=100, file_id="file-1", unique_id="unique-1"),
        )
        for index in range(2, 11):
            await runtime.telegram_dispatcher.feed_raw_update(
                bot,
                _photo_message_update(
                    30 + index,
                    user_id=100,
                    file_id=f"file-{index}",
                    unique_id=f"unique-{index}",
                ),
            )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_message_update(50, user_id=100, file_id="file-11", unique_id="unique-11"),
        )

        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        assert any("Загружено фото: 1" in text for text in sent_texts)
        assert any("Загружено фото: 10" in text for text in sent_texts)
        assert "⚠️ Можно добавить не больше 10 фотографий." in sent_texts[-1]
        assert all("Фото добавлено" not in text for text in sent_texts)
        async with service.session_factory() as session:
            photos = await TournamentPhotoRepository(session).list_for_tournament(tournament_id)
        assert len(photos) == 10
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_superadmin_repair_photo_collection_done_returns_to_repair_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, tournament_id = await _build_photo_collection_service(
        tmp_path / "repair_photo_collection.db",
        telegram_id=100,
        role=UserRole.SUPERADMIN,
    )
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    bot = RecordingBot()

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_callback_update(
                60,
                user_id=100,
                data=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
                    action=superadmin_tournament_close_kb.AdminTournamentRepairAction.ADD_PHOTO,
                    tournament_id=tournament_id,
                ).pack(),
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_message_update(61, user_id=100, file_id="file-1", unique_id="unique-1"),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_callback_update(
                62,
                user_id=100,
                data=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
                    action=superadmin_tournament_close_kb.AdminTournamentRepairAction.PHOTO_DONE,
                    tournament_id=tournament_id,
                ).pack(),
            ),
        )

        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        edited_texts = [
            call.text for call in bot.calls if call.__class__.__name__ == "EditMessageText"
        ]
        assert any("Загружено фото: 0" in text for text in sent_texts)
        assert any("Загружено фото: 1" in text for text in sent_texts)
        assert any("📸 Фотографии" in text for text in edited_texts)
        assert any("Фотографий: 1" in text for text in edited_texts)
        assert all("Фото добавлено" not in text for text in [*sent_texts, *edited_texts])
        async with service.session_factory() as session:
            photos = await TournamentPhotoRepository(session).list_for_tournament(tournament_id)
        assert len(photos) == 1
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_admin_view_single_photo_restores_control_after_photo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, tournament_id = await _build_photo_collection_service(
        tmp_path / "admin_view_single_photo.db",
        telegram_id=100,
        role=UserRole.ADMIN,
    )
    await service.add_tournament_photo(
        admin_telegram_id=100,
        tournament_id=tournament_id,
        telegram_file_id="view-file-1",
        telegram_file_unique_id="view-unique-1",
    )
    monkeypatch.setattr(admin_result_handlers, "result_service", service)
    bot = RecordingBot()

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_callback_update(
                70,
                user_id=100,
                data=admin_results_kb.AdminResultPlayerCallback(
                    action=admin_results_kb.AdminResultPlayerAction.VIEW_PHOTOS,
                    tournament_id=tournament_id,
                    page=0,
                    player_id=0,
                ).pack(),
            ),
        )

        method_names = [call.__class__.__name__ for call in bot.calls]
        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        assert method_names == ["AnswerCallbackQuery", "DeleteMessage", "SendPhoto", "SendMessage"]
        assert "📸 Фотографии" in sent_texts[-1]
        assert "Фотографий: 1" in sent_texts[-1]
        assert all("Фото добавлено" not in text for text in sent_texts)
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_admin_view_album_restores_one_control_after_album(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, tournament_id = await _build_photo_collection_service(
        tmp_path / "admin_view_album.db",
        telegram_id=100,
        role=UserRole.ADMIN,
    )
    for index in range(2):
        await service.add_tournament_photo(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            telegram_file_id=f"view-album-file-{index}",
            telegram_file_unique_id=f"view-album-unique-{index}",
        )
    monkeypatch.setattr(admin_result_handlers, "result_service", service)
    bot = RecordingBot()

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_callback_update(
                80,
                user_id=100,
                data=admin_results_kb.AdminResultPlayerCallback(
                    action=admin_results_kb.AdminResultPlayerAction.VIEW_PHOTOS,
                    tournament_id=tournament_id,
                    page=0,
                    player_id=0,
                ).pack(),
            ),
        )

        method_names = [call.__class__.__name__ for call in bot.calls]
        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        assert method_names == [
            "AnswerCallbackQuery",
            "DeleteMessage",
            "SendMediaGroup",
            "SendMessage",
        ]
        assert len([name for name in method_names if name == "SendMessage"]) == 1
        assert "📸 Фотографии" in sent_texts[-1]
        assert "Фотографий: 2" in sent_texts[-1]
        assert all("Фото добавлено" not in text for text in sent_texts)
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_superadmin_repair_view_album_restores_repair_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, engine, tournament_id = await _build_photo_collection_service(
        tmp_path / "repair_view_album.db",
        telegram_id=100,
        role=UserRole.SUPERADMIN,
    )
    for index in range(2):
        await service.add_tournament_photo(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            telegram_file_id=f"repair-view-file-{index}",
            telegram_file_unique_id=f"repair-view-unique-{index}",
        )
    monkeypatch.setattr(superadmin_close_handlers, "result_service", service)
    bot = RecordingBot()

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            _photo_callback_update(
                90,
                user_id=100,
                data=superadmin_tournament_close_kb.AdminTournamentRepairCallback(
                    action=superadmin_tournament_close_kb.AdminTournamentRepairAction.VIEW_PHOTOS,
                    tournament_id=tournament_id,
                ).pack(),
            ),
        )

        method_names = [call.__class__.__name__ for call in bot.calls]
        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        assert method_names == [
            "AnswerCallbackQuery",
            "DeleteMessage",
            "SendMediaGroup",
            "SendMessage",
        ]
        assert "📸 Фотографии" in sent_texts[-1]
        assert "Фотографий: 2" in sent_texts[-1]
        assert all("Фото добавлено" not in text for text in sent_texts)
    finally:
        await bot.session.close()
        await engine.dispose()


async def test_telegram_error_boundary_handles_unexpected_handler_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = SimpleNamespace(
        get_today_tournament_results=AsyncMock(side_effect=AttributeError("broken keyboard facade"))
    )
    monkeypatch.setattr(admin_result_handlers, "result_service", service)
    bot = RecordingBot()
    update = {
        "update_id": 9301,
        "message": {
            "message_id": 1001,
            "date": 1783598400,
            "chat": {"id": 444, "type": "private"},
            "from": {"id": 444, "is_bot": False, "first_name": "Админ"},
            "text": labels.ADMIN_PANEL_RESULTS,
        },
    }

    try:
        with caplog.at_level("ERROR", logger="app.bot.telegram.runtime"):
            await runtime.telegram_dispatcher.feed_raw_update(bot, update)

        sent_texts = [call.text for call in bot.calls if call.__class__.__name__ == "SendMessage"]
        assert sent_texts == ["Не удалось выполнить действие. Попробуйте ещё раз."]
        assert "traceback" not in sent_texts[0].lower()
        assert any("Unhandled Telegram update error" in record.message for record in caplog.records)
        assert any(getattr(record, "update_id", None) == 9301 for record in caplog.records)
        assert any(getattr(record, "telegram_user_id", None) == 444 for record in caplog.records)
    finally:
        await bot.session.close()


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
    monkeypatch.setattr(user_start_handlers, "user_access_service", service)

    await user_start_handlers.start_command(message, state)

    state.clear.assert_awaited_once()
    service.get_start_view.assert_awaited_once_with(123)
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == registration_text.REGISTRATION_GREETING
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
    monkeypatch.setattr(user_start_handlers, "user_access_service", service)

    await user_start_handlers.start_command(message, state)

    state.clear.assert_awaited_once()
    service.get_start_view.assert_awaited_once_with(123)
    assert message.answer.await_count == 1
    reply_markup = message.answer.await_args.kwargs["reply_markup"]
    assert labels.MAIN_ADMIN in keyboard_texts(reply_markup)
    assert labels.MAIN_RATING in keyboard_texts(reply_markup)
    assert labels.MAIN_HISTORY in keyboard_texts(reply_markup)
    assert labels.MAIN_HALL_OF_FAME in keyboard_texts(reply_markup)
    assert "🏆 Рейтинг" not in keyboard_texts(reply_markup)


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

    monkeypatch.setattr(
        user_start_handlers,
        "user_access_service",
        UserAccessService(session_factory),
    )
    state = SimpleNamespace(clear=AsyncMock())
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )

    try:
        await user_start_handlers.start_command(message, state)
        await user_start_handlers.start_command(message, state)

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
    user = admin_player(1, 123, role=UserRole.SUPERADMIN)
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
    monkeypatch.setattr(user_start_handlers, "user_access_service", user_service)
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", tournament_service)
    state = SimpleNamespace(clear=AsyncMock())
    start_message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    schedule_message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )

    await user_start_handlers.start_command(start_message, state)
    await user_tournament_handlers.show_tournament_schedule(schedule_message)

    user_service.get_start_view.assert_awaited_once_with(123)
    tournament_service.get_schedule_for_player.assert_awaited_once_with(123)
    assert start_message.answer.await_args.args[0] == "Админ 1, добро пожаловать!"
    assert schedule_message.answer.await_args.args[0] == (
        "Расписание турниров\n\nСреда, 8 июля — Баунти турнир"
    )


async def test_schedule_still_requires_registered_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament_service = SimpleNamespace(
        get_schedule_for_player=AsyncMock(
            side_effect=user_tournament_handlers.TournamentScheduleNotAllowedError
        )
    )
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", tournament_service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=404),
        answer=AsyncMock(),
    )

    await user_tournament_handlers.show_tournament_schedule(message)

    tournament_service.get_schedule_for_player.assert_awaited_once_with(404)
    message.answer.assert_awaited_once_with(tournament_text.SCHEDULE_UNAVAILABLE)


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

    await user_registration_handlers._delete_prompt_and_input(message, state)

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
    monkeypatch.setattr(user_start_handlers, "user_access_service", service)

    await user_start_handlers.show_club_address(message)

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
    monkeypatch.setattr(user_rating_handlers, "user_access_service", service)

    await user_rating_handlers.show_rating_menu(message)

    answer = message.answer.await_args
    assert answer.args[0] == "Какой рейтинг ты хочешь посмотреть?"
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == [
        "🏅 Текущий сезон",
        "🏅❓ За выбранный сезон",
        "🏅⏳ За все время",
        "🥊 Текущий сезон",
        "🥊❓ За выбранный сезон",
        "🥊⏳ Нокауты за все время",
        "❌ Отмена",
    ]


async def test_history_button_shows_years(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    service = SimpleNamespace(
        list_history_years=AsyncMock(
            return_value=[
                HistoryYearView(year=2026),
                HistoryYearView(year=2025),
            ]
        )
    )
    monkeypatch.setattr(user_history_handlers, "user_statistics_service", service)

    await user_history_handlers.show_history_years(message)

    service.list_history_years.assert_awaited_once_with(123)
    answer = message.answer.await_args
    assert answer.args[0] == "Выберите год"
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == [
        "2026",
        "2025",
        "❌ Отмена",
    ]


async def test_history_requires_active_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    service = SimpleNamespace(
        list_history_years=AsyncMock(side_effect=user_history_handlers.HistoryNotAllowedError)
    )
    monkeypatch.setattr(user_history_handlers, "user_statistics_service", service)

    await user_history_handlers.show_history_years(message)

    message.answer.assert_awaited_once_with("История доступна только активным игрокам.")


async def test_history_callbacks_edit_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    service = SimpleNamespace(
        list_history_months=AsyncMock(
            return_value=[
                HistoryMonthView(year=2026, month=7, label="Июль"),
                HistoryMonthView(year=2026, month=6, label="Июнь"),
            ]
        )
    )
    monkeypatch.setattr(user_history_handlers, "user_statistics_service", service)

    await user_history_handlers.show_history_months(
        callback,
        SimpleNamespace(year=2026, page=0, years_page=0),
    )

    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == "Выберите месяц\n2026 год"
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "Июль",
        "Июнь",
        "↩️ К годам",
        "❌ Отмена",
    ]


async def test_history_tournament_result_callback_formats_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    result = HistoricalTournamentResultView(
        tournament=HistoricalTournamentView(
            id=7,
            date=date(2026, 7, 17),
            display_name="Классика",
        ),
        rows=[
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="Игрок Первый",
                place=1,
                knockouts_count=3,
                big_knockouts_count=1,
                total_points=Decimal("42"),
            )
        ],
    )
    service = SimpleNamespace(get_historical_tournament_result=AsyncMock(return_value=result))
    monkeypatch.setattr(user_history_handlers, "user_statistics_service", service)

    await user_history_handlers.show_historical_tournament_result(
        callback,
        SimpleNamespace(
            tournament_id=7,
            year=2026,
            month=7,
            months_page=0,
            tournament_page=0,
            result_page=0,
        ),
    )

    message.edit_text.assert_awaited_once()
    assert "№ Игрок" in message.edit_text.await_args.args[0]
    assert "Очки" in message.edit_text.await_args.args[0]
    assert "42" in message.edit_text.await_args.args[0]
    assert "Игрок Первый" in message.edit_text.await_args.args[0]
    assert message.edit_text.await_args.kwargs["parse_mode"] == "Markdown"
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "↩️ К турнирам",
        "❌ Отмена",
    ]


async def test_hall_of_fame_button_shows_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    service = SimpleNamespace(
        get_hall_of_fame=AsyncMock(
            return_value=[
                HallOfFameSeasonView(
                    season_id=1,
                    season_name="Сезон 2026",
                    starts_at=date(2026, 1, 1),
                    champion_player_id=1,
                    champion_display_name="Иван",
                    knockout_leader_player_id=2,
                    knockout_leader_display_name="Петр",
                )
            ]
        )
    )
    monkeypatch.setattr(user_hall_of_fame_handlers, "user_statistics_service", service)

    await user_hall_of_fame_handlers.show_hall_of_fame(message)

    service.get_hall_of_fame.assert_awaited_once_with(123)
    first_answer = message.answer.await_args_list[0]
    second_answer = message.answer.await_args_list[1]
    assert first_answer.args[0] == (
        "🏆 Зал славы\n\n💍 — победитель сезона\n💥 — лучший нокаутер сезона"
    )
    assert second_answer.args[0] == ("Сезон 2026\n\n💍 Иван\n💥 Петр")
    assert "reply_markup" not in first_answer.kwargs
    assert "reply_markup" not in second_answer.kwargs
    assert first_answer.kwargs["parse_mode"] == "Markdown"
    assert second_answer.kwargs["parse_mode"] == "Markdown"


async def test_hall_of_fame_season_without_photos_is_text_card() -> None:
    message = SimpleNamespace(
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
        answer_media_group=AsyncMock(),
    )
    season = HallOfFameSeasonView(
        season_id=1,
        season_name="Лето 2026",
        starts_at=date(2026, 6, 1),
        champion_player_id=1,
        champion_display_name="Иван",
        knockout_leader_player_id=2,
        knockout_leader_display_name="Петр",
    )

    await user_hall_of_fame_handlers._send_hall_of_fame_season(message, season)

    message.answer.assert_awaited_once_with(
        "Лето 2026\n\n💍 Иван\n💥 Петр",
        parse_mode="Markdown",
    )
    message.answer_photo.assert_not_awaited()
    message.answer_media_group.assert_not_awaited()


async def test_hall_of_fame_season_with_one_photo_uses_photo_caption() -> None:
    message = SimpleNamespace(
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
        answer_media_group=AsyncMock(),
    )
    season = HallOfFameSeasonView(
        season_id=1,
        season_name="Лето 2026",
        starts_at=date(2026, 6, 1),
        champion_player_id=1,
        champion_display_name="Иван",
        knockout_leader_player_id=2,
        knockout_leader_display_name="Петр",
        champion_photo_file_id="champion-photo",
    )

    await user_hall_of_fame_handlers._send_hall_of_fame_season(message, season)

    message.answer.assert_not_awaited()
    message.answer_photo.assert_awaited_once_with(
        "champion-photo",
        caption="Лето 2026\n\n💍 Иван\n💥 Петр",
        parse_mode="Markdown",
    )
    message.answer_media_group.assert_not_awaited()


async def test_hall_of_fame_season_with_two_photos_uses_album() -> None:
    message = SimpleNamespace(
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
        answer_media_group=AsyncMock(),
    )
    season = HallOfFameSeasonView(
        season_id=1,
        season_name="Лето 2026",
        starts_at=date(2026, 6, 1),
        champion_player_id=1,
        champion_display_name="Иван",
        knockout_leader_player_id=2,
        knockout_leader_display_name="Петр",
        champion_photo_file_id="champion-photo",
        knockout_photo_file_id="knockout-photo",
    )

    await user_hall_of_fame_handlers._send_hall_of_fame_season(message, season)

    message.answer.assert_not_awaited()
    message.answer_photo.assert_not_awaited()
    media = message.answer_media_group.await_args.args[0]
    assert [item.media for item in media] == ["champion-photo", "knockout-photo"]
    assert media[0].caption == "Лето 2026\n\n💍 Иван\n💥 Петр"
    assert media[0].parse_mode == "Markdown"
    assert media[1].caption is None


async def test_superadmin_hall_of_fame_lists_completed_seasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    service = SimpleNamespace(
        list_completed_seasons=AsyncMock(
            return_value=[
                HallOfFameSeasonListItemView(
                    season_id=1,
                    season_name="Лето 2026",
                    starts_at=date(2026, 6, 1),
                    ends_at=date(2026, 8, 31),
                )
            ]
        )
    )
    monkeypatch.setattr(
        superadmin_hall_of_fame_handlers,
        "hall_of_fame_management_service",
        service,
    )
    state = MutableState()

    await superadmin_hall_of_fame_handlers.show_hall_of_fame_management(message, state)

    service.list_completed_seasons.assert_awaited_once_with(123)
    answer = message.answer.await_args
    assert answer.args[0] == "🔧 Наполнить зал славы\n\nВыбери завершённый сезон:"
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == ["Лето 2026", "❌ Отмена"]


async def test_superadmin_hall_of_fame_opens_card_and_searches_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    champion = UserView(
        id=10,
        telegram_id=None,
        display_name="Иван",
        status=UserStatus.ACTIVE,
        role=UserRole.ADMIN,
    )
    entry = HallOfFameEntryView(
        season_id=1,
        season_name="Лето 2026",
        starts_at=date(2026, 6, 1),
        ends_at=date(2026, 8, 31),
        champion=None,
        knockout_leader=None,
    )
    service = SimpleNamespace(
        get_season_hall_of_fame=AsyncMock(return_value=entry),
        search_players=AsyncMock(
            return_value=[HallOfFameCandidateView(user=champion, score=300, reason="")]
        ),
    )
    monkeypatch.setattr(
        superadmin_hall_of_fame_handlers,
        "hall_of_fame_management_service",
        service,
    )
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    state = MutableState()

    await superadmin_hall_of_fame_handlers.select_hall_of_fame_season(
        callback,
        superadmin_hall_of_fame_kb.HallOfFameSeasonCallback(
            action=superadmin_hall_of_fame_kb.HallOfFameSeasonAction.OPEN,
            page=0,
            season_id=1,
        ),
        state,
    )

    assert "🏆 Зал славы" in message.edit_text.await_args.args[0]
    assert "Не выбран" in message.edit_text.await_args.args[0]
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "💍 Выбрать чемпиона",
        "💥 Выбрать нокаутера",
        "⬅️ Назад",
        "❌ Отмена",
    ]

    search_message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        text="Иван",
        answer=AsyncMock(),
        bot=SimpleNamespace(edit_message_reply_markup=AsyncMock()),
        chat=SimpleNamespace(id=123),
    )
    await state.set_state(HallOfFameStates.entering_player_name)
    await state.update_data(
        hall_season_id=1,
        hall_field=superadmin_hall_of_fame_kb.HallOfFameField.CHAMPION.value,
    )

    await superadmin_hall_of_fame_handlers.search_hall_of_fame_player(search_message, state)

    service.search_players.assert_awaited_once_with(123, "Иван")
    search_answer = search_message.answer.await_args
    assert search_answer.args[0] == "Выбери игрока:"
    assert inline_keyboard_texts(search_answer.kwargs["reply_markup"]) == [
        "Иван",
        "⬅️ Назад",
        "❌ Отмена",
    ]


async def test_hall_of_fame_photo_prompt_is_stored_and_deleted_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = HallOfFameEntryView(
        season_id=1,
        season_name="Зима 2025",
        starts_at=date(2025, 1, 1),
        ends_at=date(2025, 3, 31),
        champion=UserView(
            id=10,
            telegram_id=None,
            display_name="Иван",
            status=UserStatus.ACTIVE,
            role=UserRole.PLAYER,
        ),
        knockout_leader=None,
    )
    service = SimpleNamespace(get_season_hall_of_fame=AsyncMock(return_value=entry))
    monkeypatch.setattr(
        superadmin_hall_of_fame_handlers,
        "hall_of_fame_management_service",
        service,
    )
    prompt_message = SimpleNamespace(message_id=701)
    source_message = SimpleNamespace(
        delete=AsyncMock(), answer=AsyncMock(return_value=prompt_message)
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=source_message,
        answer=AsyncMock(),
    )
    state = MutableState()

    await superadmin_hall_of_fame_handlers.select_hall_of_fame_card_action(
        callback,
        superadmin_hall_of_fame_kb.HallOfFameCardCallback(
            action=superadmin_hall_of_fame_kb.HallOfFameCardAction.CHAMPION_PHOTO,
            season_id=1,
            page=0,
        ),
        state,
    )

    assert state.state == HallOfFameStates.collecting_photo
    assert state.data["hall_photo_prompt_message_id"] == 701
    source_message.delete.assert_awaited_once_with()
    assert source_message.answer.await_args.args[0] == (
        "📸 Фото победителя сезона\n\nПришли одну фотографию для сезона «Зима 2025»."
    )

    photo_message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        chat=SimpleNamespace(id=123),
        bot=SimpleNamespace(delete_message=AsyncMock()),
        photo=[SimpleNamespace(file_id="small", file_unique_id="small-u")],
        answer_photo=AsyncMock(),
        answer=AsyncMock(),
    )

    await superadmin_hall_of_fame_handlers.collect_hall_of_fame_photo(photo_message, state)

    photo_message.bot.delete_message.assert_awaited_once_with(chat_id=123, message_id=701)
    photo_message.answer_photo.assert_awaited_once_with("small")
    photo_message.answer.assert_awaited_once()
    assert photo_message.answer.await_args.args[0] == (
        "Использовать это фото победителя для сезона «Зима 2025»?"
    )
    assert state.data["hall_photo_file_id"] == "small"
    assert state.data["hall_photo_file_unique_id"] == "small-u"
    assert state.data["hall_photo_prompt_message_id"] == 0


async def test_hall_of_fame_photo_prompt_delete_failure_keeps_confirmation() -> None:
    state = MutableState()
    await state.set_state(HallOfFameStates.collecting_photo)
    await state.update_data(
        hall_season_id=1,
        hall_field=superadmin_hall_of_fame_kb.HallOfFameField.KNOCKOUT.value,
        hall_season_name="Зима 2025",
        hall_photo_prompt_message_id=701,
    )
    photo_message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        chat=SimpleNamespace(id=123),
        bot=SimpleNamespace(
            delete_message=AsyncMock(
                side_effect=TelegramBadRequest(
                    method=SendMessage(chat_id=123, text="noop"),
                    message="message to delete not found",
                )
            )
        ),
        photo=[SimpleNamespace(file_id="knockout-photo", file_unique_id="knockout-unique")],
        answer_photo=AsyncMock(),
        answer=AsyncMock(),
    )

    await superadmin_hall_of_fame_handlers.collect_hall_of_fame_photo(photo_message, state)

    photo_message.answer_photo.assert_awaited_once_with("knockout-photo")
    photo_message.answer.assert_awaited_once()
    assert photo_message.answer.await_args.args[0] == (
        "Использовать это фото лучшего нокаутера для сезона «Зима 2025»?"
    )


def test_superadmin_hall_of_fame_photo_buttons_follow_assigned_slots() -> None:
    champion = UserView(
        id=10,
        telegram_id=None,
        display_name="Иван",
        status=UserStatus.ACTIVE,
        role=UserRole.PLAYER,
    )
    knockout = UserView(
        id=11,
        telegram_id=None,
        display_name="Петр",
        status=UserStatus.ACTIVE,
        role=UserRole.PLAYER,
    )
    champion_only = HallOfFameEntryView(
        season_id=1,
        season_name="Лето 2026",
        starts_at=date(2026, 6, 1),
        ends_at=date(2026, 8, 31),
        champion=champion,
        knockout_leader=None,
    )
    full_entry = HallOfFameEntryView(
        season_id=1,
        season_name="Лето 2026",
        starts_at=date(2026, 6, 1),
        ends_at=date(2026, 8, 31),
        champion=champion,
        knockout_leader=knockout,
        champion_photo_file_id="champion-photo",
    )

    assert inline_keyboard_texts(
        superadmin_hall_of_fame_kb.season_card_keyboard(entry=champion_only, page=0)
    ) == [
        "💍 Выбрать чемпиона",
        "💥 Выбрать нокаутера",
        "💍📸 Прикрепить фото победителя",
        "⬅️ Назад",
        "❌ Отмена",
    ]
    assert inline_keyboard_texts(
        superadmin_hall_of_fame_kb.season_card_keyboard(entry=full_entry, page=0)
    ) == [
        "💍 Выбрать чемпиона",
        "💥 Выбрать нокаутера",
        "💍📸 Заменить фото победителя",
        "💥📸 Прикрепить фото нокаутера",
        "⬅️ Назад",
        "❌ Отмена",
    ]


async def test_hall_of_fame_requires_active_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    service = SimpleNamespace(
        get_hall_of_fame=AsyncMock(side_effect=user_hall_of_fame_handlers.HallOfFameNotAllowedError)
    )
    monkeypatch.setattr(user_hall_of_fame_handlers, "user_statistics_service", service)

    await user_hall_of_fame_handlers.show_hall_of_fame(message)

    message.answer.assert_awaited_once_with("Зал славы доступен только активным игрокам.")


async def test_history_cancel_deletes_message_and_sends_confirmation() -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())

    await user_history_handlers.cancel_history(callback)

    callback.answer.assert_awaited_once_with("История закрыта")
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with("История закрыта")


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
    monkeypatch.setattr(user_rating_handlers, "rating_service", rating_service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(kind=RatingKind.CURRENT_SEASON, page=0)

    await user_rating_handlers.show_rating(callback, callback_data)

    rating_service.get_rating_for_player.assert_awaited_once_with(
        telegram_id=123,
        kind=RatingKind.CURRENT_SEASON,
        season_id=None,
    )
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == (
        "Рейтинг — текущий сезон\n"
        "💍 - победитель сезона\n"
        "🎲 - количество турниров\n\n"
        "👉 1. *Игрок Первый* — 120 | 🎲 3"
    )
    assert message.edit_text.await_args.kwargs["parse_mode"] == "Markdown"
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["1-1 из 1", "⬅️ Назад", "❌ Закрыть рейтинг"]


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
    monkeypatch.setattr(user_rating_handlers, "rating_service", rating_service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(kind=RatingKind.CURRENT_SEASON, page=-1)

    await user_rating_handlers.show_rating(callback, callback_data)

    assert "11. Игрок 11" in message.edit_text.await_args.args[0]
    assert "*Игрок 12*" in message.edit_text.await_args.args[0]
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["⬅️", "11-12 из 12", "⬅️ Назад", "❌ Закрыть рейтинг"]


async def test_rating_selected_season_picker_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seasons = [
        SeasonOptionView(id=2, name="Лето 2026", starts_at=date(2026, 6, 1), ends_at=None),
        SeasonOptionView(
            id=1,
            name="Весна 2026",
            starts_at=date(2026, 3, 1),
            ends_at=date(2026, 5, 31),
        ),
    ]
    rating_service = SimpleNamespace(
        list_rating_seasons=AsyncMock(return_value=seasons),
        get_rating_for_player=AsyncMock(
            return_value=RatingResultView(
                title="Рейтинг — Весна 2026",
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
        ),
    )
    monkeypatch.setattr(user_rating_handlers, "rating_service", rating_service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )

    await user_rating_handlers.show_rating_season_picker(
        callback,
        user_rating_kb.RatingSeasonPageCallback(kind=RatingKind.SELECTED_SEASON, page=0),
    )

    rating_service.list_rating_seasons.assert_awaited_once_with(123)
    assert message.edit_text.await_args.args[0] == "Выбери сезон."
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "Лето 2026",
        "Весна 2026",
        "⬅️ Назад",
        "❌ Отмена",
    ]

    await user_rating_handlers.show_rating_for_selected_season(
        callback,
        user_rating_kb.RatingSeasonCallback(
            kind=RatingKind.SELECTED_SEASON,
            season_id=1,
            season_page=0,
        ),
    )

    rating_service.get_rating_for_player.assert_awaited_once_with(
        telegram_id=123,
        kind=RatingKind.SELECTED_SEASON,
        season_id=1,
    )
    assert "Рейтинг — Весна 2026" in message.edit_text.await_args.args[0]


async def test_rating_menu_cancel_deletes_message() -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    callback_data = SimpleNamespace(action=user_rating_kb.RatingCancelAction.CANCEL)

    await user_rating_handlers.cancel_rating(callback, callback_data)

    callback.answer.assert_awaited_once_with("Отмена")
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with("Отмена")


async def test_rating_close_deletes_message() -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    callback_data = SimpleNamespace(action=user_rating_kb.RatingCancelAction.CLOSE)

    await user_rating_handlers.cancel_rating(callback, callback_data)

    callback.answer.assert_awaited_once_with("Рейтинг закрыт")
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with("Рейтинг закрыт")


async def test_rating_back_returns_root_menu() -> None:
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    callback_data = SimpleNamespace(action=user_rating_kb.RatingCancelAction.BACK)

    await user_rating_handlers.cancel_rating(callback, callback_data)

    callback.answer.assert_awaited_once_with()
    assert message.edit_text.await_args.args[0] == "Какой рейтинг ты хочешь посмотреть?"


async def test_profile_button_shows_two_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    service = SimpleNamespace(require_active_user=AsyncMock(return_value=active_player()))
    monkeypatch.setattr(user_profile_handlers, "user_access_service", service)

    await user_profile_handlers.show_profile_menu(message)

    answer = message.answer.await_args
    assert answer.args[0] == "За какой период ты хочешь посмотреть свои достижения?"
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == [
        "🏆 Текущий сезон",
        "🏆❓ За выбранный сезон",
        "⏳ За все время",
        "❌ Отмена",
    ]


async def test_profile_callback_sends_selected_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_service = SimpleNamespace(
        get_profile_for_player=AsyncMock(return_value=("Твой профиль — текущий сезон", None)),
        list_prize_tournaments_for_player=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(user_profile_handlers, "profile_service", profile_service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(kind=ProfileKind.CURRENT_SEASON)

    await user_profile_handlers.show_profile(callback, callback_data)

    profile_service.get_profile_for_player.assert_awaited_once_with(
        telegram_id=123,
        kind=ProfileKind.CURRENT_SEASON,
        season_id=None,
    )
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == (
        "Твой профиль — текущий сезон\n\nПрофиль не найден. Нажми /start."
    )
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "⬅️ Назад",
        "❌ Закрыть",
    ]
    profile_service.list_prize_tournaments_for_player.assert_not_awaited()


async def test_profile_callback_shows_details_button_when_prizes_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = PlayerProfileView(
        display_name="Дима",
        total_points=Decimal("3250"),
        knockouts_count=14,
        big_knockouts_count=0,
        tournaments_count=27,
        first_places_count=1,
        second_places_count=0,
        third_places_count=0,
        fourth_places_count=0,
        fifth_places_count=0,
        rating_position=7,
        rating_participants_count=44,
        prize_percent=41,
    )
    prize = PlayerPrizeTournamentView(
        tournament_id=10,
        date=date(2026, 8, 15),
        display_name="Double",
        place=1,
    )
    profile_service = SimpleNamespace(
        get_profile_for_player=AsyncMock(return_value=("Твой профиль — текущий сезон", stats)),
        list_prize_tournaments_for_player=AsyncMock(return_value=[prize]),
    )
    monkeypatch.setattr(user_profile_handlers, "profile_service", profile_service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )

    await user_profile_handlers.show_profile(
        callback,
        user_profile_kb.ProfileCallback(kind=ProfileKind.CURRENT_SEASON),
    )

    assert (
        "⭐ 3250 (7 место из 44) | 🎯 41% | 🥊 14 | 🎲 27" in (message.edit_text.await_args.args[0])
    )
    assert "Под кнопкой «Подробнее»" in message.edit_text.await_args.args[0]
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "Подробнее",
        "⬅️ Назад",
        "❌ Закрыть",
    ]


async def test_profile_selected_season_picker_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seasons = [
        SeasonOptionView(id=2, name="Лето 2026", starts_at=date(2026, 6, 1), ends_at=None),
        SeasonOptionView(
            id=1,
            name="Весна 2026",
            starts_at=date(2026, 3, 1),
            ends_at=date(2026, 5, 31),
        ),
    ]
    profile_service = SimpleNamespace(
        list_profile_seasons=AsyncMock(return_value=seasons),
        get_profile_for_player=AsyncMock(return_value=("Твой профиль — Весна 2026", None)),
        list_prize_tournaments_for_player=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(user_profile_handlers, "profile_service", profile_service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )

    await user_profile_handlers.show_profile_season_picker(
        callback,
        user_profile_kb.ProfileSeasonPageCallback(page=0),
    )

    profile_service.list_profile_seasons.assert_awaited_once_with(123)
    assert message.edit_text.await_args.args[0] == "Выбери сезон."
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "Лето 2026",
        "Весна 2026",
        "⬅️ Назад",
        "❌ Отмена",
    ]

    await user_profile_handlers.show_profile_for_selected_season(
        callback,
        user_profile_kb.ProfileSeasonCallback(season_id=1, season_page=0),
    )

    profile_service.get_profile_for_player.assert_awaited_once_with(
        telegram_id=123,
        kind=ProfileKind.SELECTED_SEASON,
        season_id=1,
    )
    assert message.edit_text.await_args.args[0] == (
        "Твой профиль — Весна 2026\n\nПрофиль не найден. Нажми /start."
    )


async def test_profile_details_list_and_tournament_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prizes = [
        PlayerPrizeTournamentView(
            tournament_id=index,
            date=date(2026, 8, 20 - index),
            display_name=f"Type {index}",
            place=(index % 5) + 1,
        )
        for index in range(1, 7)
    ]
    profile_service = SimpleNamespace(
        list_prize_tournaments_for_player=AsyncMock(return_value=prizes),
    )
    history_result = HistoricalTournamentResultView(
        tournament=HistoricalTournamentView(
            id=2,
            date=date(2026, 8, 18),
            display_name="Type 2",
        ),
        rows=[
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="Дима",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
                bonus_points=0,
                total_points=Decimal("42"),
            )
        ],
    )
    statistics_service = SimpleNamespace(
        get_historical_tournament_result=AsyncMock(return_value=history_result),
    )
    monkeypatch.setattr(user_profile_handlers, "profile_service", profile_service)
    monkeypatch.setattr(user_profile_handlers, "user_statistics_service", statistics_service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )

    await user_profile_handlers.show_profile_prize_tournaments(
        callback,
        user_profile_kb.ProfileDetailsPageCallback(
            kind=ProfileKind.ALL_TIME,
            page=0,
        ),
    )

    assert message.edit_text.await_args.args[0].startswith("История достижений")
    buttons = inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"])
    assert buttons[:5] == [
        "🥈 19.08.26 — Type 1",
        "🥉 18.08.26 — Type 2",
        "4️⃣ 17.08.26 — Type 3",
        "5️⃣ 16.08.26 — Type 4",
        "🥇 15.08.26 — Type 5",
    ]
    assert "1 из 2" in buttons
    assert "➡️" in buttons
    assert "⬅️ Назад" in buttons
    assert "❌ Закрыть" in buttons

    await user_profile_handlers.show_profile_prize_tournament_result(
        callback,
        user_profile_kb.ProfilePrizeTournamentCallback(
            tournament_id=2,
            kind=ProfileKind.ALL_TIME,
            list_page=0,
        ),
    )

    statistics_service.get_historical_tournament_result.assert_awaited_once_with(
        telegram_id=123,
        tournament_id=2,
    )
    assert "⏳ История" in message.edit_text.await_args.args[0]
    assert "Type 2" in message.edit_text.await_args.args[0]
    assert "Очки" in message.edit_text.await_args.args[0]
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "⬅️ Назад",
        "❌ Закрыть",
    ]


async def test_profile_cancel_deletes_message_and_sends_confirmation() -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())

    await user_profile_handlers.cancel_profile(callback)

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
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", tournament_service)

    await user_tournament_handlers.show_tournaments_for_registration(message, state)

    answer = message.answer.await_args
    assert answer.args[0] == "Выбери турниры, на которые хочешь записаться."
    button = answer.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Среда, 8 июля — Неопределённый турнир"
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
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", tournament_service)

    await user_tournament_handlers.show_tournaments_for_registration(message, state)

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
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", tournament_service)

    await user_tournament_handlers.show_tournaments_for_registration(message, state)

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
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", service)
    message = SimpleNamespace(edit_reply_markup=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=user_tournaments_kb.TournamentListAction.PAGE,
        page=1,
        tournament_id=0,
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"tournament_registration_selection": [1]}),
        update_data=AsyncMock(),
    )

    await user_tournament_handlers.register_for_tournament(callback, callback_data, state)

    state.update_data.assert_awaited_once_with(tournament_registration_selection=[1])
    callback.answer.assert_awaited_once_with()
    rows = message.edit_reply_markup.await_args.kwargs["reply_markup"].inline_keyboard
    assert rows[0][0].text == "Вторник, 7 июля — Неопределённый турнир"
    assert [button.text for button in rows[1]] == ["⬅️", "7-7 из 7"]


async def test_multiple_tournament_registration_sends_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournaments = [
        tournament_view(7, date(2026, 7, 8), 1, "Баунти турнир"),
        tournament_view(8, date(2026, 7, 9), 2, "Классика"),
    ]
    service = SimpleNamespace(register_player_for_tournaments=AsyncMock(return_value=tournaments))
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", service)
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

    await user_tournament_handlers.confirm_tournament_registration(callback, state)

    service.register_player_for_tournaments.assert_awaited_once_with(
        telegram_id=123,
        tournament_ids=[7, 8],
    )
    message.delete.assert_awaited_once_with()
    confirmation = message.answer.await_args.args[0]
    assert "Ты записан на турниры:" in confirmation
    assert "Среда, 8 июля — Баунти турнир" in confirmation
    assert "Четверг, 9 июля — Классика" in confirmation
    assert "• Среда, 8 июля — Баунти турнир" not in confirmation
    assert "• Четверг, 9 июля — Классика" not in confirmation
    assert "ты отменишь запись заранее" in confirmation


async def test_tournament_registration_selection_can_be_cancelled() -> None:
    message = SimpleNamespace(
        delete=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    state = SimpleNamespace(update_data=AsyncMock())

    await user_tournament_handlers.cancel_tournament_registration_selection(callback, state)

    state.update_data.assert_awaited_once_with(tournament_registration_selection=[])
    callback.answer.assert_awaited_once_with("Отмена")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with("Отмена")


async def test_cancellation_button_reports_when_player_has_no_registrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(get_player_upcoming_registrations=AsyncMock(return_value=[]))
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(update_data=AsyncMock())

    await user_tournament_handlers.show_tournaments_for_cancellation(message, state)

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
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", service)
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

    await user_tournament_handlers.confirm_tournament_cancellation(callback, state)

    service.cancel_player_tournament_registrations.assert_awaited_once_with(
        telegram_id=123,
        tournament_ids=[7, 8],
    )
    message.delete.assert_awaited_once_with()
    confirmation = message.answer.await_args.args[0]
    assert "Ты отменил запись на турниры:" in confirmation
    assert "Среда, 8 июля — Баунти турнир" in confirmation
    assert "Четверг, 9 июля — Классика" in confirmation
    assert "• Среда, 8 июля — Баунти турнир" not in confirmation
    assert "• Четверг, 9 июля — Классика" not in confirmation


async def test_tournament_cancellation_after_check_in_shows_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        cancel_player_tournament_registrations=AsyncMock(
            side_effect=TournamentRegistrationAlreadyCheckedInError
        )
    )
    monkeypatch.setattr(user_tournament_handlers, "tournament_service", service)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"tournament_cancellation_selection": [7]}),
        update_data=AsyncMock(),
    )

    await user_tournament_handlers.confirm_tournament_cancellation(callback, state)

    callback.answer.assert_awaited_once_with(
        "Вы уже прошли check-in на этот турнир.\nОтменить запись после check-in нельзя.",
        show_alert=True,
    )
    state.update_data.assert_not_awaited()


async def test_tournament_cancellation_selection_can_be_cancelled() -> None:
    message = SimpleNamespace(
        delete=AsyncMock(),
        answer=AsyncMock(),
    )
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    state = SimpleNamespace(update_data=AsyncMock())

    await user_tournament_handlers.cancel_tournament_cancellation_selection(callback, state)

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
    superadmins = [
        UserView(
            id=1,
            telegram_id=100,
            display_name="Админ Первый",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        ),
    ]
    service = SimpleNamespace(
        get_registration_notification=AsyncMock(
            return_value=RegistrationNotificationView(
                request=request,
                admins=superadmins,
                candidates=[],
            )
        ),
    )
    monkeypatch.setattr(notifications, "registration_review_service", service)

    await notifications.notify_admins_about_registration(bot, request.id)

    service.get_registration_notification.assert_awaited_once_with(10)
    assert bot.send_message.await_count == 1
    assert bot.send_message.await_args_list[0].kwargs["chat_id"] == 100
    assert "Telegram ID" not in bot.send_message.await_args_list[0].kwargs["text"]


async def test_new_player_name_input_shows_confirmation_without_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        validate_new_player_display_name=AsyncMock(),
        submit_new_player_registration=AsyncMock(),
    )
    monkeypatch.setattr(user_registration_handlers, "registration_service", service)
    state = MutableState()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="  Antony   Easy ",
        chat=SimpleNamespace(id=100),
        bot=SimpleNamespace(delete_message=AsyncMock()),
        delete=AsyncMock(),
        answer=AsyncMock(),
    )

    await user_registration_handlers.enter_new_display_name(message, state)

    service.validate_new_player_display_name.assert_awaited_once_with("Antony Easy")
    service.submit_new_player_registration.assert_not_awaited()
    assert state.state == user_registration_handlers.RegistrationStates.confirming_new_display_name
    assert state.data["new_player_display_name"] == "Antony Easy"
    answer = message.answer.await_args
    assert answer.args[0] == registration_text.new_player_confirmation("Antony Easy")
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == [
        "✅ Подтвердить",
        "✏️ Изменить",
        "❌ Отмена",
    ]


async def test_new_player_confirmation_creates_request_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = RegistrationRequestView(
        id=10,
        telegram_id=100,
        request_type="new_player",
        status="pending",
        requested_display_name="Antony Easy",
        requested_link_name=None,
        candidate_user_id=None,
        created_at="01.01.2026 12:00",
    )
    service = SimpleNamespace(submit_new_player_registration=AsyncMock(return_value=request))
    notify = AsyncMock()
    monkeypatch.setattr(user_registration_handlers, "registration_service", service)
    monkeypatch.setattr(user_registration_handlers, "notify_admins_about_registration", notify)
    state = MutableState()
    await state.update_data(new_player_display_name="Antony Easy")
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        bot=SimpleNamespace(),
        answer=AsyncMock(),
    )

    await user_registration_handlers.confirm_new_player_registration(callback, state)

    service.submit_new_player_registration.assert_awaited_once_with(100, "Antony Easy")
    notify.assert_awaited_once_with(callback.bot, 10)
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with(registration_text.REGISTRATION_SUBMITTED)
    assert state.data == {}


async def test_admin_panel_entry_sends_admin_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[]))
    )
    monkeypatch.setattr(admin_panel_handlers, "user_access_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_panel_handlers.open_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == "Добро пожаловать в админ-панель."
    assert keyboard_texts(answer.kwargs["reply_markup"]) == [
        "✅ Чек-ин",
        "🏁 Внести результат",
        "👑 Суперадмин",
        "⬅️ Выход",
    ]


async def test_admin_panel_entry_hides_superadmin_button_for_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.ADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[]))
    )
    monkeypatch.setattr(admin_panel_handlers, "user_access_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_panel_handlers.open_admin_panel(message)

    assert keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == [
        "✅ Чек-ин",
        "🏁 Внести результат",
        "⬅️ Выход",
    ]


async def test_superadmin_panel_denies_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(require_superadmin=AsyncMock(side_effect=AdminAccessDeniedError))
    monkeypatch.setattr(superadmin_panel_handlers, "user_access_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await superadmin_panel_handlers.open_superadmin_panel(message)

    service.require_superadmin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once_with("Недостаточно прав.")


async def test_superadmin_panel_button_opens_superadmin_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.SUPERADMIN)
    service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    monkeypatch.setattr(superadmin_panel_handlers, "user_access_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await superadmin_panel_handlers.open_superadmin_panel(message)

    service.require_superadmin.assert_awaited_once_with(100)
    assert message.answer.await_args.args[0] == "Суперадмин."
    reply_markup = message.answer.await_args.kwargs["reply_markup"]
    assert keyboard_rows(reply_markup) == [
        ["📝 Регистрации", "✏️ Переименовать пользователя"],
        ["🔒 Закрыть турнир", "➕ Добавить администратора"],
        ["🗓 Календарь", "🔧 Наполнить зал славы"],
        ["⬅️ Админка"],
    ]
    assert "📝 Заявки на регистрацию" not in keyboard_texts(reply_markup)
    assert "🛠 Админка" not in keyboard_texts(reply_markup)
    assert "⬅️ Выход" not in keyboard_texts(reply_markup)


async def test_superadmin_panel_back_returns_admin_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[]))
    )
    monkeypatch.setattr(admin_panel_handlers, "user_access_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_panel_handlers.back_to_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    assert admin.role == UserRole.SUPERADMIN
    assert admin.status == UserStatus.ACTIVE
    assert message.answer.await_args.args[0] == "Добро пожаловать в админ-панель."
    assert keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == [
        "✅ Чек-ин",
        "🏁 Внести результат",
        "👑 Суперадмин",
        "⬅️ Выход",
    ]


async def test_superadmin_rename_button_prompts_for_user_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(require_rename_access=AsyncMock())
    monkeypatch.setattr(superadmin_user_handlers, "user_rename_service", service)
    state = MutableState()
    prompt = SimpleNamespace(message_id=77)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(return_value=prompt),
    )

    await superadmin_user_handlers.prompt_user_rename_search(message, state)

    service.require_rename_access.assert_awaited_once_with(100)
    assert state.state == UserRenameStates.entering_current_name
    assert state.data == {"user_rename_prompt_message_id": 77}
    answer = message.answer.await_args
    assert answer.args[0] == "✏️ Переименовать пользователя\n\nВведи имя пользователя."
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == ["❌ Отмена"]


async def test_superadmin_rename_search_shows_multiple_users_without_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = [
        UserView(1, None, "Иван Иванов", UserStatus.ACTIVE, UserRole.PLAYER),
        UserView(2, 200, "Иван Админ", UserStatus.ACTIVE, UserRole.ADMIN),
    ]
    service = SimpleNamespace(search_users_for_rename=AsyncMock(return_value=candidates))
    monkeypatch.setattr(superadmin_user_handlers, "user_rename_service", service)
    state = MutableState()
    await state.update_data(user_rename_prompt_message_id=77)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="Иван",
        chat=SimpleNamespace(id=100),
        bot=SimpleNamespace(edit_message_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )

    await superadmin_user_handlers.search_user_to_rename(message, state)

    service.search_users_for_rename.assert_awaited_once_with(100, "Иван")
    assert message.bot.edit_message_reply_markup.await_count == 1
    answer = message.answer.await_args
    assert answer.args[0] == "Выбери пользователя:"
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == [
        "Иван Иванов",
        "Иван Админ",
        "⬅️ Назад",
        "❌ Отмена",
    ]


async def test_superadmin_rename_new_name_confirmation_does_not_mutate_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(validate_new_display_name=AsyncMock(return_value="иван петров"))
    monkeypatch.setattr(superadmin_user_handlers, "user_rename_service", service)
    state = MutableState()
    await state.update_data(target_user_id=10, old_display_name="Иван Иванов")
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="  Иван   Петров ",
        answer=AsyncMock(),
    )

    await superadmin_user_handlers.enter_new_user_display_name(message, state)

    service.validate_new_display_name.assert_awaited_once_with(100, 10, "Иван Петров")
    assert state.state == UserRenameStates.confirming_user_rename
    assert state.data["new_display_name"] == "Иван Петров"
    answer = message.answer.await_args
    assert "Иван Иванов" in answer.args[0]
    assert "Иван Петров?" in answer.args[0]
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == [
        "✅ Переименовать",
        "⬅️ Назад",
        "❌ Отмена",
    ]
    assert not hasattr(service, "rename_user")


async def test_superadmin_rename_cancel_clears_state_and_returns_menu() -> None:
    state = MutableState()
    await state.update_data(target_user_id=10, old_display_name="Иван Иванов")
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        answer=AsyncMock(),
        message=message,
    )

    await superadmin_user_handlers._cancel_user_rename(callback, state)

    callback.answer.assert_awaited_once_with("Отмена.")
    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == "Отмена."
    assert "✏️ Переименовать пользователя" in keyboard_texts(answer.kwargs["reply_markup"])
    assert state.data == {}
    assert state.state is None


async def test_superadmin_rename_stale_confirmation_does_not_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(rename_user=AsyncMock())
    monkeypatch.setattr(superadmin_user_handlers, "user_rename_service", service)
    state = MutableState()
    callback = SimpleNamespace(
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=100),
        message=SimpleNamespace(delete=AsyncMock(), answer=AsyncMock()),
    )

    await superadmin_user_handlers.confirm_user_rename(
        callback,
        superadmin_users_kb.UserRenameConfirmCallback(
            action=superadmin_users_kb.UserRenameConfirmAction.CONFIRM,
            user_id=10,
        ),
        state,
    )

    callback.answer.assert_awaited_once_with(
        "Данные устарели. Открой переименование заново.",
        show_alert=True,
    )
    service.rename_user.assert_not_awaited()


async def test_superadmin_rename_confirm_updates_and_does_not_notify_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renamed = UserView(10, 555, "Иван Петров", UserStatus.ACTIVE, UserRole.PLAYER)
    service = SimpleNamespace(rename_user=AsyncMock(return_value=renamed))
    monkeypatch.setattr(superadmin_user_handlers, "user_rename_service", service)
    state = MutableState()
    await state.update_data(
        target_user_id=10,
        old_display_name="Иван Иванов",
        new_display_name="Иван Петров",
    )
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=100),
        message=message,
        bot=bot,
    )

    await superadmin_user_handlers.confirm_user_rename(
        callback,
        superadmin_users_kb.UserRenameConfirmCallback(
            action=superadmin_users_kb.UserRenameConfirmAction.CONFIRM,
            user_id=10,
        ),
        state,
    )

    service.rename_user.assert_awaited_once_with(100, 10, "Иван Петров", "Иван Иванов")
    bot.send_message.assert_not_called()
    callback.answer.assert_awaited_once_with(
        "✅ Пользователь переименован\n\nИван Иванов → Иван Петров"
    )
    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == "✅ Пользователь переименован\n\nИван Иванов → Иван Петров"
    assert state.data == {}
    assert state.state is None


async def test_admin_calendar_button_shows_inline_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.SUPERADMIN)
    service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    monkeypatch.setattr(admin_calendar_handlers, "user_access_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_calendar_handlers.open_admin_calendar(message)

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
    service = SimpleNamespace(require_add_admin_access=AsyncMock())
    monkeypatch.setattr(superadmin_administrator_handlers, "admin_management_service", service)
    state = MutableState()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(return_value=SimpleNamespace(message_id=55)),
    )

    await superadmin_administrator_handlers.prompt_admin_candidate_search(message, state)

    service.require_add_admin_access.assert_awaited_once_with(100)
    assert state.state == superadmin_administrator_handlers.AdminAddStates.entering_candidate_name
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "Введи ник игрока"
    assert inline_keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == ["❌ Отмена"]
    assert state.data["admin_candidate_prompt_message_id"] == 55


async def test_add_admin_button_denies_regular_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        require_add_admin_access=AsyncMock(side_effect=AdminAccessDeniedError)
    )
    monkeypatch.setattr(superadmin_administrator_handlers, "admin_management_service", service)
    state = MutableState()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await superadmin_administrator_handlers.prompt_admin_candidate_search(message, state)

    message.answer.assert_awaited_once_with("Недостаточно прав.")


async def test_add_admin_search_with_one_candidate_shows_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = active_player()
    service = SimpleNamespace(
        search_admin_candidates_for_superadmin=AsyncMock(return_value=[candidate])
    )
    monkeypatch.setattr(superadmin_administrator_handlers, "admin_management_service", service)
    state = MutableState()
    await state.update_data(admin_candidate_prompt_message_id=77)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="Игрок",
        chat=SimpleNamespace(id=100),
        bot=SimpleNamespace(edit_message_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )

    await superadmin_administrator_handlers.search_admin_candidate(message, state)

    service.search_admin_candidates_for_superadmin.assert_awaited_once_with(100, "Игрок")
    message.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=100,
        message_id=77,
        reply_markup=None,
    )
    answer = message.answer.await_args
    assert answer.args[0] == "Назначить администратором:\n\nИгрок Первый?"
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == [
        "✅ Назначить",
        "↩️ Назад",
        "❌ Отмена",
    ]


async def test_add_admin_search_with_multiple_candidates_shows_names_without_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = [
        active_player(),
        UserView(
            id=2,
            telegram_id=124,
            display_name="Игрок Второй",
            status=UserStatus.ACTIVE,
            role=UserRole.PLAYER,
        ),
    ]
    service = SimpleNamespace(
        search_admin_candidates_for_superadmin=AsyncMock(return_value=candidates)
    )
    monkeypatch.setattr(superadmin_administrator_handlers, "admin_management_service", service)
    state = MutableState()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="Игрок",
        answer=AsyncMock(),
    )

    await superadmin_administrator_handlers.search_admin_candidate(message, state)

    answer = message.answer.await_args
    assert answer.args[0] == "Выбери игрока:"
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == [
        "Игрок Первый",
        "Игрок Второй",
        "🔎 Искать снова",
        "❌ Отмена",
    ]


async def test_add_admin_search_not_found_keeps_search_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(search_admin_candidates_for_superadmin=AsyncMock(return_value=[]))
    monkeypatch.setattr(superadmin_administrator_handlers, "admin_management_service", service)
    state = MutableState()
    await state.set_state(superadmin_administrator_handlers.AdminAddStates.entering_candidate_name)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="Нет такого",
        answer=AsyncMock(),
    )

    await superadmin_administrator_handlers.search_admin_candidate(message, state)

    assert state.state == superadmin_administrator_handlers.AdminAddStates.entering_candidate_name
    answer = message.answer.await_args
    assert answer.args[0] == "Игроки не найдены.\n\nПопробуй ввести другое имя."
    assert inline_keyboard_texts(answer.kwargs["reply_markup"]) == [
        "🔎 Искать снова",
        "❌ Отмена",
    ]


async def test_add_admin_prompt_cancel_clears_state_without_mutation() -> None:
    state = MutableState()
    await state.set_state(superadmin_administrator_handlers.AdminAddStates.entering_candidate_name)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await superadmin_administrator_handlers.select_admin_candidate(
        callback,
        superadmin_administrators_kb.AdminCandidateCallback(
            action=superadmin_administrators_kb.AdminCandidateAction.CANCEL,
            player_id=0,
        ),
        state,
    )

    callback.answer.assert_awaited_once_with("Отмена.")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once_with("Отмена.")
    assert state.state is None
    assert state.data == {}


async def test_confirm_add_admin_promotes_player_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    promoted = admin_player(2, 200, UserRole.ADMIN)

    class UserAccessServiceContractFake:
        def __init__(self) -> None:
            self.calls: list[dict[str, int]] = []

        async def add_admin(self, *, superadmin_telegram_id: int, user_id: int) -> UserView:
            self.calls.append(
                {
                    "superadmin_telegram_id": superadmin_telegram_id,
                    "user_id": user_id,
                }
            )
            return promoted

    service = UserAccessServiceContractFake()
    monkeypatch.setattr(superadmin_administrator_handlers, "admin_management_service", service)
    state = MutableState()
    bot = SimpleNamespace(send_message=AsyncMock())
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
        bot=bot,
    )
    callback_data = SimpleNamespace(
        action=superadmin_administrators_kb.AdminAddAction.CONFIRM,
        player_id=2,
    )

    await superadmin_administrator_handlers.confirm_add_admin(callback, callback_data, state)

    assert service.calls == [{"superadmin_telegram_id": 100, "user_id": 2}]
    callback.answer.assert_awaited_once_with("✅ Админ 2 назначен администратором.")
    message.delete.assert_awaited_once_with()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "✅ Админ 2 назначен администратором."
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 200
    assert bot.send_message.await_args.kwargs["text"] == "Тебе назначена роль админа."
    assert "🛠 Админ-панель" in keyboard_texts(bot.send_message.await_args.kwargs["reply_markup"])


async def test_admin_calendar_seasons_callback_shows_timeline_management(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.SUPERADMIN)
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    season_service = SimpleNamespace(
        get_season_timeline=AsyncMock(return_value=season_timeline_view())
    )
    monkeypatch.setattr(admin_calendar_handlers, "user_access_service", user_service)
    monkeypatch.setattr(admin_calendar_handlers, "season_service", season_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(action=admin_calendar_kb.AdminCalendarAction.SEASONS)
    state = SimpleNamespace(set_state=AsyncMock(), update_data=AsyncMock(), clear=AsyncMock())

    await admin_calendar_handlers.select_admin_calendar_section(callback, callback_data, state)

    user_service.require_superadmin.assert_awaited_once_with(100)
    season_service.get_season_timeline.assert_awaited_once_with(100)
    state.set_state.assert_not_awaited()
    state.update_data.assert_not_awaited()
    state.clear.assert_awaited_once()
    message.delete.assert_awaited_once_with()
    answer = message.answer.await_args
    assert answer.args[0] == (
        "🏆 Сезоны\n\n"
        "Текущий сезон:\n"
        "Лето 2026\n"
        "с 1 июня 2026\n"
        "без даты окончания\n\n"
        "Будущий сезон отсутствует."
    )
    assert [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ] == ["➕ Создать следующий сезон", "📋 Все сезоны", "❌ Отмена"]


def test_season_creation_preview_shows_active_season_transition_from_dto() -> None:
    preview = SeasonCreationPreviewView(
        name="Осень 2026",
        starts_at=date(2026, 8, 10),
        scoring_config_id=1,
        active_season_ends_at=date(2026, 8, 9),
    )

    assert season_fmt.proposal(preview) == (
        "🏆 Новый сезон\n\n"
        "Название: Осень 2026\n"
        "Дата начала: 10 августа 2026\n\n"
        "Текущий сезон завершится: 9.08.2026\n"
        "Новый сезон начнётся: 10.08.2026"
    )


async def test_admin_calendar_tournaments_callback_shows_stateless_plan_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.SUPERADMIN)
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    planning_service = SimpleNamespace(
        inspect_next_week=AsyncMock(
            return_value=WeeklyPlanningCheckView(
                status=WeeklyPlanningStatus.READY,
                plan=tournament_plan_view(),
            )
        )
    )
    monkeypatch.setattr(admin_calendar_handlers, "user_access_service", user_service)
    monkeypatch.setattr(admin_calendar_handlers, "tournament_planning_service", planning_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock(), update_data=AsyncMock())

    await admin_calendar_handlers.select_admin_calendar_section(
        callback,
        SimpleNamespace(action=admin_calendar_kb.AdminCalendarAction.TOURNAMENTS),
        state,
    )

    planning_service.inspect_next_week.assert_awaited_once_with(100)
    state.clear.assert_awaited_once()
    state.update_data.assert_not_called()
    message.delete.assert_awaited_once_with()
    assert message.answer.await_args_list[0].args[0] == (
        "Суперадмин. На будущую неделю нужно создать турниры!"
    )
    answer = message.answer.await_args_list[1]
    assert answer.args[0] == (
        "Будет создано расписание:\n\n"
        "Среда, 22 июля — Баунти турнир\n"
        "Четверг, 23 июля — Классика\n"
        "Пятница, 24 июля — Фризаут\n"
        "Суббота, 25 июля — Double Double\n"
        "Воскресенье, 26 июля — Mystery Bounty"
    )
    assert [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ] == ["Изменить", "Создать", "Отмена"]


async def test_admin_calendar_tournaments_callback_shows_in_progress_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.SUPERADMIN)
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin))
    planning_service = SimpleNamespace(
        inspect_next_week=AsyncMock(
            return_value=WeeklyPlanningCheckView(
                status=WeeklyPlanningStatus.BLOCKED_BY_ACTIVE_WEEK,
                schedule=weekly_fact_view(),
            )
        )
    )
    monkeypatch.setattr(admin_calendar_handlers, "user_access_service", user_service)
    monkeypatch.setattr(admin_calendar_handlers, "tournament_planning_service", planning_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock(), update_data=AsyncMock())

    await admin_calendar_handlers.select_admin_calendar_section(
        callback,
        SimpleNamespace(action=admin_calendar_kb.AdminCalendarAction.TOURNAMENTS),
        state,
    )

    message.answer.assert_awaited_once_with(
        "✅ Турниры на эту неделю уже созданы\n\n"
        "Среда, 12 августа — Баунти турнир\n"
        "Четверг, 13 августа — Классика\n"
        "Пятница, 14 августа — Фризаут\n"
        "Суббота, 15 августа — Double Double\n"
        "Воскресенье, 16 августа — Boss Bounty\n\n"
        "Следующее расписание можно будет создать после завершения текущей игровой недели."
    )


def test_tournament_management_callback_routes_do_not_collide() -> None:
    top_level = admin_calendar_kb.AdminCalendarCallback(
        action=admin_calendar_kb.AdminCalendarAction.TOURNAMENTS
    ).pack()
    plan_edit = admin_calendar_kb.CalendarPlanCallback(
        action=admin_calendar_kb.CalendarPlanAction.EDIT
    ).pack()
    day_edit = admin_schedule_kb.TournamentPlanDayEditCallback(
        tournament_date="2026-07-23",
    ).pack()
    type_edit = admin_schedule_kb.TournamentTypeEditCallback(
        tournament_date="2026-07-23",
        tournament_type_id=2,
    ).pack()

    assert top_level.startswith("admin_calendar:")
    assert top_level == "admin_calendar:tournaments"
    assert plan_edit.startswith("calendar_plan:")
    assert day_edit.startswith("tour_plan_day:")
    assert type_edit.startswith("tournament_type_edit:")
    assert len({top_level, plan_edit, day_edit, type_edit}) == 4


async def test_admin_calendar_plan_denies_regular_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planning_service = SimpleNamespace(
        get_plan_view=AsyncMock(side_effect=AdminAccessDeniedError),
    )
    monkeypatch.setattr(admin_schedule_handlers, "tournament_planning_service", planning_service)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                admin_schedule_handlers.FSM_PLAN_KEY: [
                    {"date": "2026-07-22", "tournament_type_id": 1},
                    {"date": "2026-07-23", "tournament_type_id": 2},
                    {"date": "2026-07-24", "tournament_type_id": 3},
                    {"date": "2026-07-25", "tournament_type_id": 4},
                    {"date": "2026-07-26", "tournament_type_id": 5},
                ]
            }
        ),
        clear=AsyncMock(),
    )

    await admin_schedule_handlers.review_calendar_plan(
        callback,
        SimpleNamespace(action=admin_calendar_kb.CalendarPlanAction.EDIT),
        state,
    )

    callback.answer.assert_awaited_once_with("Недостаточно прав.", show_alert=True)


async def test_admin_calendar_plan_sends_public_schedule_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tournament_plan_view()
    schedule = WeeklyScheduleView(
        tournaments=[
            WeeklyScheduleTournamentView(
                id=1,
                date=date(2026, 7, 22),
                tournament_type_code="bounty",
                tournament_type_name="Баунти турнир",
                description=None,
                entry_fee=600,
                entry_stack=20_000,
                addon_fee=800,
                addon_stack=125_000,
                rebuys=[TournamentRebuyView(fee=600, stack=30_000)],
                knockout_mode="small_big",
                points_multiplier=Decimal("1.00"),
                prize_place_multiplier=Decimal("1.00"),
                prize_place_multiplier_places=None,
            )
        ]
    )
    planning_service = SimpleNamespace(
        create_weekly_schedule=AsyncMock(return_value=plan),
    )
    schedule_service = SimpleNamespace(
        get_created_weekly_schedule=AsyncMock(return_value=schedule),
    )
    monkeypatch.setattr(admin_schedule_handlers, "tournament_planning_service", planning_service)
    monkeypatch.setattr(admin_schedule_handlers, "tournament_schedule_service", schedule_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                admin_schedule_handlers.FSM_PLAN_KEY: [
                    {"date": item.date.isoformat(), "tournament_type_id": item.tournament_type.id}
                    for item in plan.tournaments
                ]
            }
        ),
        clear=AsyncMock(),
    )

    await admin_schedule_handlers.review_calendar_plan(
        callback,
        SimpleNamespace(action=admin_calendar_kb.CalendarPlanAction.CONFIRM),
        state,
    )

    planning_service.create_weekly_schedule.assert_awaited_once()
    schedule_service.get_created_weekly_schedule.assert_awaited_once()
    state.clear.assert_awaited_once()
    assert message.answer.await_args_list[0].args[0].startswith("Создано расписание:")
    assert (
        message.answer.await_args_list[1]
        .args[0]
        .startswith("🔥 РАСПИСАНИЕ ТУРНИРОВ ПОКЕРНОГО КЛУБА «ГАМБИТ»")
    )


async def test_tournament_edit_button_shows_day_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tournament_plan_view()
    planning_service = SimpleNamespace(get_plan_view=AsyncMock(return_value=plan))
    monkeypatch.setattr(admin_schedule_handlers, "tournament_planning_service", planning_service)
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                admin_schedule_handlers.FSM_PLAN_KEY: [
                    {"date": item.date.isoformat(), "tournament_type_id": item.tournament_type.id}
                    for item in plan.tournaments
                ]
            }
        ),
        clear=AsyncMock(),
    )
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_schedule_handlers.review_calendar_plan(
        callback,
        SimpleNamespace(action=admin_calendar_kb.CalendarPlanAction.EDIT),
        state,
    )

    message.delete.assert_awaited_once_with()
    assert message.answer.await_args.args[0] == "Что меняем?"
    assert [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ] == ["Среда", "Четверг", "Пятница", "Суббота", "Воскресенье", "⬅️ Назад"]


async def test_tournament_edit_button_starts_fsm_from_stateless_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tournament_plan_view()
    planning_service = SimpleNamespace(build_next_week_plan=AsyncMock(return_value=plan))
    monkeypatch.setattr(admin_schedule_handlers, "tournament_planning_service", planning_service)
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={}),
        update_data=AsyncMock(),
        clear=AsyncMock(),
    )
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_schedule_handlers.review_calendar_plan(
        callback,
        SimpleNamespace(action=admin_calendar_kb.CalendarPlanAction.EDIT),
        state,
    )

    planning_service.build_next_week_plan.assert_awaited_once_with(100)
    state.update_data.assert_awaited_once()
    assert state.update_data.await_args.kwargs[admin_schedule_handlers.FSM_PLAN_KEY][0] == {
        "date": "2026-07-22",
        "tournament_type_id": 1,
    }
    assert message.answer.await_args.args[0] == "Что меняем?"


async def test_tournament_day_selection_shows_type_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edit_view = TournamentPlanDayEditView(
        tournament_date=date(2026, 7, 22),
        tournament_types=[
            TournamentTypeOptionView(id=1, name="Баунти турнир"),
            TournamentTypeOptionView(id=2, name="Классика"),
        ],
    )
    planning_service = SimpleNamespace(get_day_edit_options=AsyncMock(return_value=edit_view))
    monkeypatch.setattr(admin_schedule_handlers, "tournament_planning_service", planning_service)
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                admin_schedule_handlers.FSM_PLAN_KEY: [
                    {"date": "2026-07-22", "tournament_type_id": 1},
                    {"date": "2026-07-23", "tournament_type_id": 2},
                    {"date": "2026-07-24", "tournament_type_id": 3},
                    {"date": "2026-07-25", "tournament_type_id": 4},
                    {"date": "2026-07-26", "tournament_type_id": 5},
                ]
            }
        )
    )
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_schedule_handlers.select_tournament_plan_day(
        callback,
        SimpleNamespace(tournament_date="2026-07-22"),
        state,
    )

    planning_service.get_day_edit_options.assert_awaited_once()
    assert message.answer.await_args.args[0] == "Выбери тип турнира:\nСреда, 22 июля"
    assert [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ] == ["Баунти турнир", "Классика", "Удалить день", "⬅️ Назад"]


async def test_tournament_type_selection_updates_fsm_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updated = tournament_plan_view()
    planning_service = SimpleNamespace(update_plan_day_type=AsyncMock(return_value=updated))
    monkeypatch.setattr(admin_schedule_handlers, "tournament_planning_service", planning_service)
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                admin_schedule_handlers.FSM_PLAN_KEY: [
                    {"date": "2026-07-22", "tournament_type_id": 1},
                    {"date": "2026-07-23", "tournament_type_id": 2},
                    {"date": "2026-07-24", "tournament_type_id": 3},
                    {"date": "2026-07-25", "tournament_type_id": 4},
                    {"date": "2026-07-26", "tournament_type_id": 5},
                ]
            }
        ),
        update_data=AsyncMock(),
    )
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_schedule_handlers.select_tournament_type(
        callback,
        SimpleNamespace(tournament_date="2026-07-23", tournament_type_id=3),
        state,
    )

    planning_service.update_plan_day_type.assert_awaited_once()
    state.update_data.assert_awaited_once()
    assert state.update_data.await_args.kwargs[admin_schedule_handlers.FSM_PLAN_KEY][1] == {
        "date": "2026-07-23",
        "tournament_type_id": 3,
    }


async def test_tournament_day_delete_updates_fsm_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updated = tournament_plan_view(
        tournaments=[
            item for item in tournament_plan_view().tournaments if item.date != date(2026, 7, 25)
        ]
    )
    planning_service = SimpleNamespace(remove_plan_day=AsyncMock(return_value=updated))
    monkeypatch.setattr(admin_schedule_handlers, "tournament_planning_service", planning_service)
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                admin_schedule_handlers.FSM_PLAN_KEY: [
                    {"date": "2026-07-22", "tournament_type_id": 1},
                    {"date": "2026-07-23", "tournament_type_id": 2},
                    {"date": "2026-07-24", "tournament_type_id": 3},
                    {"date": "2026-07-25", "tournament_type_id": 4},
                    {"date": "2026-07-26", "tournament_type_id": 5},
                ]
            }
        ),
        update_data=AsyncMock(),
    )
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await admin_schedule_handlers.delete_tournament_plan_day(
        callback,
        SimpleNamespace(tournament_date="2026-07-25"),
        state,
    )

    planning_service.remove_plan_day.assert_awaited_once()
    state.update_data.assert_awaited_once()
    assert state.update_data.await_args.kwargs[admin_schedule_handlers.FSM_PLAN_KEY] == [
        {"date": "2026-07-22", "tournament_type_id": 1},
        {"date": "2026-07-23", "tournament_type_id": 2},
        {"date": "2026-07-24", "tournament_type_id": 3},
        {"date": "2026-07-26", "tournament_type_id": 5},
    ]
    assert "Суббота, 25 июля" not in message.answer.await_args.args[0]


async def test_enter_season_name_prompts_for_start_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_service = SimpleNamespace(require_superadmin=AsyncMock(return_value=admin_player(1, 100)))
    season_service = SimpleNamespace(
        get_creation_preview=AsyncMock(side_effect=superadmin_season_handlers.SeasonStartDateError)
    )
    monkeypatch.setattr(superadmin_season_handlers, "user_access_service", user_service)
    monkeypatch.setattr(superadmin_season_handlers, "season_service", season_service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="Осень 2026",
        answer=AsyncMock(),
    )
    state = SimpleNamespace(update_data=AsyncMock(), set_state=AsyncMock(), clear=AsyncMock())

    await superadmin_season_handlers.enter_season_name(message, state)

    state.update_data.assert_awaited_once_with(season_name="Осень 2026")
    state.set_state.assert_awaited_once_with(
        superadmin_season_handlers.CalendarSeasonCreationStates.entering_starts_at
    )
    message.answer.assert_awaited_once()


async def test_enter_season_start_date_returns_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = SeasonCreationPreviewView(
        name="Осень 2026",
        starts_at=date(2026, 9, 1),
        scoring_config_id=1,
    )
    season_service = SimpleNamespace(get_creation_preview=AsyncMock(return_value=preview))
    monkeypatch.setattr(superadmin_season_handlers, "season_service", season_service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        text="1.09.2026",
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={"season_name": "Осень 2026"}),
        update_data=AsyncMock(),
        set_state=AsyncMock(),
        clear=AsyncMock(),
    )

    await superadmin_season_handlers.enter_season_starts_at(message, state)

    season_service.get_creation_preview.assert_awaited_once_with(
        100,
        name="Осень 2026",
        starts_at=date(2026, 9, 1),
    )
    state.update_data.assert_awaited_once_with(season_starts_at="2026-09-01")
    state.set_state.assert_awaited_once_with(None)
    assert message.answer.await_args.args[0] == (
        "🏆 Новый сезон\n\nНазвание: Осень 2026\nДата начала: 1 сентября 2026"
    )


async def test_confirm_season_creation_calls_public_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    season_service = SimpleNamespace(create_next_season=AsyncMock(return_value=season_view()))
    monkeypatch.setattr(superadmin_season_handlers, "season_service", season_service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={"season_name": "Осень 2026", "season_starts_at": "2026-09-01"}
        ),
        clear=AsyncMock(),
    )

    await superadmin_season_handlers.select_season_open_action(
        callback,
        SimpleNamespace(action=superadmin_seasons_kb.SeasonOpenAction.CONFIRM),
        state,
    )

    season_service.create_next_season.assert_awaited_once_with(
        admin_telegram_id=100,
        name="Осень 2026",
        starts_at=date(2026, 9, 1),
    )
    state.clear.assert_awaited_once()
    callback.answer.assert_awaited_once_with("Сезон создан.")
    message.delete.assert_awaited_once_with()


async def test_admin_panel_registration_requests_button_shows_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_registrations_overview_for_superadmin=AsyncMock(
            return_value=registrations_overview(),
        ),
        list_pending_reviews_page_for_superadmin=AsyncMock(
            return_value=Page(items=[], page=0, page_size=5, total_items=0)
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await superadmin_registration_handlers.show_pending_registrations(message)

    service.get_registrations_overview_for_superadmin.assert_awaited_once_with(100)
    service.list_pending_reviews_page_for_superadmin.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "Регистраций нет."
    assert "reply_markup" not in message.answer.await_args.kwargs


async def test_admin_panel_registration_requests_button_shows_paginated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviews = [registration_review(player_id) for player_id in range(10, 15)]
    service = SimpleNamespace(
        get_registrations_overview_for_superadmin=AsyncMock(
            return_value=registrations_overview(pending_count=6),
        ),
        list_pending_reviews_page_for_superadmin=AsyncMock(
            return_value=Page(items=reviews, page=0, page_size=5, total_items=6)
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await superadmin_registration_handlers.show_pending_registrations(message)

    service.get_registrations_overview_for_superadmin.assert_awaited_once_with(100)
    service.list_pending_reviews_page_for_superadmin.assert_awaited_once_with(
        100,
        page=0,
        page_size=5,
    )
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == "Регистрации"
    buttons = [
        button.text for row in answer.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert buttons == [
        "Игрок 10",
        "Игрок 11",
        "Игрок 12",
        "Игрок 13",
        "Игрок 14",
        "1/2",
        "➡️",
        "❌ Отмена",
    ]


async def test_registrations_button_shows_hub_when_both_registration_types_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_registrations_overview_for_superadmin=AsyncMock(
            return_value=registrations_overview(pending_count=2, tournament_count=3),
        ),
        list_pending_reviews_page_for_superadmin=AsyncMock(),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(from_user=SimpleNamespace(id=100), answer=AsyncMock())

    await superadmin_registration_handlers.show_pending_registrations(message)

    service.get_registrations_overview_for_superadmin.assert_awaited_once_with(100)
    service.list_pending_reviews_page_for_superadmin.assert_not_awaited()
    assert message.answer.await_args.args[0] == "Регистрации"
    assert inline_keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == [
        "📝 Регистрации новых пользователей",
        "🎲 Регистрации на турниры",
        "❌ Отмена",
    ]


async def test_registrations_button_opens_tournament_counts_without_back_when_user_requests_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_registrations_overview_for_superadmin=AsyncMock(
            return_value=registrations_overview(tournament_count=14),
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(from_user=SimpleNamespace(id=100), answer=AsyncMock())

    await superadmin_registration_handlers.show_pending_registrations(message)

    assert message.answer.await_args.args[0] == (
        "🎲 Регистрации на турниры\n\nСреда, 19 августа — Баунти\nЗарегистрировано: 14"
    )
    assert inline_keyboard_texts(message.answer.await_args.kwargs["reply_markup"]) == ["❌ Отмена"]


async def test_registrations_hub_opens_tournament_counts_with_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_registrations_overview_for_superadmin=AsyncMock(
            return_value=registrations_overview(pending_count=2, tournament_count=9),
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )

    await superadmin_registration_handlers.registrations_hub(
        callback,
        superadmin_registrations_kb.RegistrationsHubCallback(
            action=superadmin_registrations_kb.RegistrationsHubAction.TOURNAMENTS,
        ),
    )

    callback.answer.assert_awaited_once_with()
    assert message.edit_text.await_args.args[0] == (
        "🎲 Регистрации на турниры\n\nСреда, 19 августа — Баунти\nЗарегистрировано: 9"
    )
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "⬅️ Назад",
        "❌ Отмена",
    ]


def test_registration_list_keyboard_hides_pagination_for_one_pending() -> None:
    page = Page(items=[registration_review(10)], page=0, page_size=5, total_items=1)

    keyboard = superadmin_registrations_kb.registration_list_keyboard(page)

    assert inline_keyboard_texts(keyboard) == ["Игрок 10", "❌ Отмена"]


def test_registration_list_keyboard_hides_pagination_for_five_pending() -> None:
    page = Page(
        items=[registration_review(player_id) for player_id in range(10, 15)],
        page=0,
        page_size=5,
        total_items=5,
    )

    keyboard = superadmin_registrations_kb.registration_list_keyboard(page)

    assert inline_keyboard_texts(keyboard) == [
        "Игрок 10",
        "Игрок 11",
        "Игрок 12",
        "Игрок 13",
        "Игрок 14",
        "❌ Отмена",
    ]


def test_registration_list_keyboard_shows_pagination_for_six_pending() -> None:
    page = Page(
        items=[registration_review(player_id) for player_id in range(10, 15)],
        page=0,
        page_size=5,
        total_items=6,
    )

    keyboard = superadmin_registrations_kb.registration_list_keyboard(page)

    assert inline_keyboard_texts(keyboard) == [
        "Игрок 10",
        "Игрок 11",
        "Игрок 12",
        "Игрок 13",
        "Игрок 14",
        "1/2",
        "➡️",
        "❌ Отмена",
    ]


async def test_admin_registration_list_page_callback_edits_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviews = [registration_review(15)]
    service = SimpleNamespace(
        list_pending_reviews_page_for_superadmin=AsyncMock(
            return_value=Page(items=reviews, page=1, page_size=5, total_items=6)
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationListAction.PAGE,
        page=1,
        request_id=0,
    )

    await superadmin_registration_handlers.review_registration_list(callback, callback_data)

    service.list_pending_reviews_page_for_superadmin.assert_awaited_once_with(
        100,
        page=1,
        page_size=5,
    )
    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == "Регистрации"
    buttons = [
        button.text
        for row in message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert buttons == ["Игрок 15", "⬅️", "2/2", "❌ Отмена"]


async def test_admin_registration_list_cancel_deletes_message() -> None:
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(message=message, answer=AsyncMock())
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationListAction.CANCEL,
        page=0,
        request_id=0,
    )

    await superadmin_registration_handlers.review_registration_list(callback, callback_data)

    callback.answer.assert_awaited_once_with("Заявка скрыта")
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == "Суперадмин."


async def test_admin_registration_list_open_edits_message_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = registration_review(10)
    service = SimpleNamespace(get_registration_review_for_admin=AsyncMock(return_value=review))
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationListAction.OPEN,
        page=0,
        request_id=10,
    )

    await superadmin_registration_handlers.review_registration_list(callback, callback_data)

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
    assert buttons == ["✅ Одобрить", "🚫 Отклонить", "↩️ Назад", "❌ Отмена"]


async def test_admin_registration_list_open_suppresses_not_modified_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = registration_review(10)
    service = SimpleNamespace(get_registration_review_for_admin=AsyncMock(return_value=review))
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(
        text="Регистрации",
        reply_markup=None,
        edit_text=AsyncMock(
            side_effect=TelegramBadRequest(
                method=SendMessage(chat_id=1, text="test"),
                message="Bad Request: message is not modified",
            )
        ),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationListAction.OPEN,
        page=0,
        request_id=10,
    )

    await superadmin_registration_handlers.review_registration_list(callback, callback_data)

    service.get_registration_review_for_admin.assert_awaited_once_with(
        admin_telegram_id=100,
        request_id=10,
    )
    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()


async def test_registration_review_back_returns_to_source_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = Page(items=[registration_review(15)], page=1, page_size=5, total_items=6)
    service = SimpleNamespace(
        list_pending_reviews_page_for_superadmin=AsyncMock(return_value=page),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationReviewAction.BACK,
        request_id=10,
        page=1,
    )

    await superadmin_registration_handlers.review_registration(callback, callback_data)

    service.list_pending_reviews_page_for_superadmin.assert_awaited_once_with(
        100,
        page=1,
        page_size=5,
    )
    assert message.edit_text.await_args.args[0] == "Регистрации"
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "Игрок 15",
        "⬅️",
        "2/2",
        "❌ Отмена",
    ]


async def test_registration_review_dispatcher_card_back_returns_to_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = registration_review(10)
    page = Page(items=[review], page=0, page_size=5, total_items=1)
    service = SimpleNamespace(
        get_registration_review_for_admin=AsyncMock(return_value=review),
        list_pending_reviews_page_for_superadmin=AsyncMock(return_value=page),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    bot = RecordingBot()

    def callback_update(update_id: int, data: str, text: str) -> dict[str, object]:
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"registration-callback-{update_id}",
                "from": {"id": 100, "is_bot": False, "first_name": "Админ"},
                "message": {
                    "message_id": 10,
                    "date": 1783598400,
                    "chat": {"id": 100, "type": "private"},
                    "text": text,
                },
                "chat_instance": "chat-instance",
                "data": data,
            },
        }

    try:
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                1,
                superadmin_registrations_kb.RegistrationListCallback(
                    action=superadmin_registrations_kb.RegistrationListAction.OPEN,
                    page=0,
                    request_id=10,
                ).pack(),
                "Регистрации",
            ),
        )
        await runtime.telegram_dispatcher.feed_raw_update(
            bot,
            callback_update(
                2,
                superadmin_registrations_kb.RegistrationReviewCallback(
                    action=superadmin_registrations_kb.RegistrationReviewAction.BACK,
                    page=0,
                    request_id=10,
                ).pack(),
                "Новая заявка на регистрацию",
            ),
        )

        edited_texts = [
            call.text for call in bot.calls if call.__class__.__name__ == "EditMessageText"
        ]
        assert len(edited_texts) == 2
        assert "Новая заявка на регистрацию" in edited_texts[0]
        assert edited_texts[1] == "Регистрации"
        last_edit = [call for call in bot.calls if call.__class__.__name__ == "EditMessageText"][-1]
        assert inline_keyboard_texts(last_edit.reply_markup) == ["Игрок 10", "❌ Отмена"]
    finally:
        await bot.session.close()


def test_registration_review_back_callback_returns_to_list() -> None:
    keyboard = superadmin_registrations_kb.registration_review_keyboard(request_id=10, page=1)
    back_button = next(
        button for row in keyboard.inline_keyboard for button in row if button.text == "↩️ Назад"
    )

    callback_data = superadmin_registrations_kb.RegistrationReviewCallback.unpack(
        back_button.callback_data or ""
    )

    assert callback_data.action == superadmin_registrations_kb.RegistrationReviewAction.BACK
    assert callback_data.request_id == 10
    assert callback_data.page == 1


def test_registration_candidate_selection_back_callback_returns_to_card() -> None:
    review = registration_review(10)
    keyboard = superadmin_registrations_kb.registration_candidate_selection_keyboard(
        request_id=10,
        candidates=review.candidates,
        page=1,
    )
    back_button = next(
        button for row in keyboard.inline_keyboard for button in row if button.text == "↩️ Назад"
    )

    callback_data = superadmin_registrations_kb.RegistrationListCallback.unpack(
        back_button.callback_data or ""
    )

    assert callback_data.action == superadmin_registrations_kb.RegistrationListAction.OPEN
    assert callback_data.request_id == 10
    assert callback_data.page == 1


async def test_admin_panel_exit_returns_main_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = admin_player(1, 100, UserRole.SUPERADMIN)
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(return_value=AdminPanelView(admin=admin, reviews=[]))
    )
    monkeypatch.setattr(admin_calendar_handlers, "user_access_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_calendar_handlers.exit_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once()
    answer = message.answer.await_args
    assert answer.args[0] == "Главное меню."
    assert labels.MAIN_ADMIN in keyboard_texts(answer.kwargs["reply_markup"])


async def test_admin_panel_denies_regular_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        get_admin_panel_for_admin=AsyncMock(side_effect=AdminAccessDeniedError)
    )
    monkeypatch.setattr(admin_panel_handlers, "user_access_service", service)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )

    await admin_panel_handlers.open_admin_panel(message)

    service.get_admin_panel_for_admin.assert_awaited_once_with(100)
    message.answer.assert_awaited_once_with("У тебя нет доступа в админ-панель!")


async def test_registration_review_keyboard_with_history_has_action_labels() -> None:
    keyboard = superadmin_registrations_kb.registration_review_keyboard(
        request_id=10,
        can_select_candidate=True,
        can_approve=False,
    )

    buttons = [button.text for row in keyboard.inline_keyboard for button in row]
    assert buttons == [
        "👤 Выбрать игрока",
        "🚫 Отклонить",
        "↩️ Назад",
        "❌ Отмена",
    ]
    assert [len(row) for row in keyboard.inline_keyboard] == [1, 1, 1, 1]


def test_link_registration_review_with_one_candidate_is_user_friendly() -> None:
    review = RegistrationReviewView(
        request=RegistrationRequestView(
            id=10,
            telegram_id=200,
            request_type="link_existing_player",
            status="pending",
            requested_display_name=None,
            requested_link_name="Лиза Савинкова",
            candidate_user_id=None,
            created_at="08.08.2026 14:19",
        ),
        candidates=[registration_candidate(20, 100)],
    )

    rendered = notifications.format_registration_review(review)
    keyboard = superadmin_registrations_kb.registration_review_keyboard_for_review(review)

    assert rendered == (
        "Новая заявка на регистрацию\n\n"
        "Тип: привязка к истории\n"
        "Искали: Лиза Савинкова\n"
        "Создана: 08.08.2026 14:19\n\n"
        "Найден игрок:\n"
        "Исторический 20"
    )
    assert "id 20" not in rendered
    assert "1." not in rendered
    assert "имя" not in rendered
    assert inline_keyboard_texts(keyboard) == [
        "✅ Привязать",
        "🚫 Отклонить",
        "↩️ Назад",
        "❌ Отмена",
    ]


def test_link_registration_review_with_multiple_candidates_requires_selection() -> None:
    review = RegistrationReviewView(
        request=RegistrationRequestView(
            id=10,
            telegram_id=200,
            request_type="link_existing_player",
            status="pending",
            requested_display_name=None,
            requested_link_name="Лиза Савинкова",
            candidate_user_id=None,
            created_at="08.08.2026 14:19",
        ),
        candidates=[registration_candidate(20, 100), registration_candidate(21, 92)],
    )

    rendered = notifications.format_registration_review(review)
    keyboard = superadmin_registrations_kb.registration_review_keyboard_for_review(review)

    assert "Найдено несколько похожих игроков." in rendered
    assert "Исторический 20" not in rendered
    assert "100%" not in rendered
    assert inline_keyboard_texts(keyboard) == [
        "👤 Выбрать игрока",
        "🚫 Отклонить",
        "↩️ Назад",
        "❌ Отмена",
    ]


def test_link_registration_review_without_candidates_has_safe_fallback() -> None:
    review = RegistrationReviewView(
        request=RegistrationRequestView(
            id=10,
            telegram_id=200,
            request_type="link_existing_player",
            status="pending",
            requested_display_name=None,
            requested_link_name="Лиза Савинкова",
            candidate_user_id=None,
            created_at="08.08.2026 14:19",
        ),
        candidates=[],
    )

    rendered = notifications.format_registration_review(review)
    keyboard = superadmin_registrations_kb.registration_review_keyboard_for_review(review)

    assert "Подходящий игрок больше не найден." in rendered
    assert inline_keyboard_texts(keyboard) == ["🚫 Отклонить", "↩️ Назад", "❌ Отмена"]


async def test_registration_review_cancel_deletes_message_without_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        approve_registration=AsyncMock(),
        reject_registration=AsyncMock(),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationReviewAction.CANCEL,
        request_id=10,
        page=0,
    )

    await superadmin_registration_handlers.review_registration(callback, callback_data)

    callback.answer.assert_awaited_once_with("Заявка скрыта")
    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once()
    service.approve_registration.assert_not_awaited()
    service.reject_registration.assert_not_awaited()


async def test_registration_review_reject_deletes_pending_and_notifies_superadmins(
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
    reviewer = admin_player(1, 100, UserRole.SUPERADMIN)
    other_superadmin = admin_player(2, 101, UserRole.SUPERADMIN)
    service = SimpleNamespace(
        reject_registration=AsyncMock(
            return_value=RegistrationReviewResultView(
                user=None,
                request=request,
                admins=[reviewer, other_superadmin],
            )
        ),
        list_pending_reviews_page_for_superadmin=AsyncMock(
            return_value=Page(items=[], page=0, page_size=5, total_items=0)
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_text=AsyncMock(),
        answer=AsyncMock(),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        bot=bot,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationReviewAction.REJECT,
        request_id=10,
        page=0,
    )

    await superadmin_registration_handlers.review_registration(callback, callback_data)

    service.reject_registration.assert_awaited_once_with(
        superadmin_telegram_id=100,
        request_id=10,
    )
    service.list_pending_reviews_page_for_superadmin.assert_awaited_once_with(
        100,
        page=0,
        page_size=5,
    )
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == "Заявок на регистрацию нет."
    assert callback.answer.await_args.args[0] == "Заявка отклонена"
    assert bot.send_message.await_count == 2
    admin_call, player_call = bot.send_message.await_args_list
    assert admin_call.kwargs["chat_id"] == 101
    assert "Заявка отклонена: Админ 1" in admin_call.kwargs["text"]
    assert player_call.kwargs["chat_id"] == 200
    assert player_call.kwargs["text"] == registration_text.REGISTRATION_REJECTED


async def test_registration_review_result_moves_empty_last_page_to_previous_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = RegistrationRequestView(
        id=15,
        telegram_id=200,
        request_type="new_player",
        status="approved",
        requested_display_name="Игрок 15",
        requested_link_name=None,
        candidate_user_id=None,
        created_at="27.07.2026 12:00",
    )
    service = SimpleNamespace(
        approve_registration=AsyncMock(
            return_value=RegistrationReviewResultView(
                user=active_player(),
                request=request,
                admins=[admin_player(1, 100, UserRole.SUPERADMIN)],
            )
        ),
        list_pending_reviews_page_for_superadmin=AsyncMock(
            return_value=Page(
                items=[registration_review(14)],
                page=0,
                page_size=5,
                total_items=1,
            )
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(text="review", edit_text=AsyncMock())
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        bot=bot,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationReviewAction.APPROVE,
        request_id=15,
        page=1,
    )

    await superadmin_registration_handlers.review_registration(callback, callback_data)

    service.list_pending_reviews_page_for_superadmin.assert_awaited_once_with(
        100,
        page=1,
        page_size=5,
    )
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "Игрок 14",
        "❌ Отмена",
    ]


async def test_registration_review_with_multiple_matches_shows_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matches = [registration_candidate(20, 100), registration_candidate(21, 92)]
    request = RegistrationRequestView(
        id=10,
        telegram_id=200,
        request_type="link_existing_player",
        status="pending",
        requested_display_name=None,
        requested_link_name="Исторический",
        candidate_user_id=None,
        created_at="27.07.2026 12:00",
    )
    review = RegistrationReviewView(
        request=request,
        candidates=matches,
    )
    service = SimpleNamespace(
        get_registration_review_for_admin=AsyncMock(return_value=review),
        approve_registration=AsyncMock(),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_text=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationReviewAction.SELECT_CANDIDATE,
        request_id=10,
        page=1,
    )

    await superadmin_registration_handlers.review_registration(callback, callback_data)

    service.get_registration_review_for_admin.assert_awaited_once_with(
        admin_telegram_id=100,
        request_id=10,
    )
    service.approve_registration.assert_not_awaited()
    callback.answer.assert_awaited_once_with()
    message.edit_text.assert_awaited_once()
    selection_keyboard = message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [button.text for row in selection_keyboard.inline_keyboard for button in row]
    assert buttons == [
        "Исторический 20",
        "Исторический 21",
        "↩️ Назад",
        "❌ Отмена",
    ]


async def test_selected_registration_candidate_shows_confirmation_without_mutation(
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
        candidates=[registration_candidate(21, 100)],
        selected_candidate=registration_candidate(21, 100),
    )
    service = SimpleNamespace(select_registration_candidate=AsyncMock(return_value=review))
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_text=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(request_id=10, user_id=21, page=1)

    await superadmin_registration_handlers.select_registration_candidate(callback, callback_data)

    service.select_registration_candidate.assert_awaited_once_with(
        superadmin_telegram_id=100,
        request_id=10,
        user_id=21,
    )
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == (
        "Привязать Telegram-пользователя к игроку:\n\nИсторический 21?"
    )
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "✅ Привязать",
        "↩️ Назад",
        "❌ Отмена",
    ]
    callback.answer.assert_awaited_once_with("Игрок выбран.")


async def test_confirm_selected_registration_candidate_links_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = UserView(
        id=21,
        telegram_id=200,
        display_name="Исторический 21",
        status=UserStatus.ACTIVE,
        role=UserRole.PLAYER,
    )
    request = RegistrationRequestView(
        id=10,
        telegram_id=200,
        request_type="link_existing_player",
        status="approved",
        requested_display_name=None,
        requested_link_name="Исторический",
        candidate_user_id=None,
        created_at="27.07.2026 12:00",
    )
    service = SimpleNamespace(
        approve_registration=AsyncMock(
            return_value=RegistrationReviewResultView(
                user=player,
                request=request,
                admins=[admin_player(1, 100, UserRole.SUPERADMIN)],
            )
        ),
        list_pending_reviews_page_for_superadmin=AsyncMock(
            return_value=Page(items=[], page=0, page_size=5, total_items=0)
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(text="confirmation", edit_text=AsyncMock(), answer=AsyncMock())
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        bot=bot,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationCandidateConfirmAction.CONFIRM,
        request_id=10,
        user_id=21,
        page=0,
    )

    await superadmin_registration_handlers.confirm_registration_candidate(
        callback,
        callback_data,
    )

    service.approve_registration.assert_awaited_once_with(
        superadmin_telegram_id=100,
        request_id=10,
        candidate_user_id=21,
    )
    service.list_pending_reviews_page_for_superadmin.assert_awaited_once_with(
        100,
        page=0,
        page_size=5,
    )
    callback.answer.assert_awaited_once_with("Заявка одобрена")
    message.edit_text.assert_awaited_once()


async def test_registration_candidate_confirmation_back_returns_to_candidate_list(
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
            candidate_user_id=None,
            created_at="27.07.2026 12:00",
        ),
        candidates=[registration_candidate(20, 100), registration_candidate(21, 92)],
    )
    service = SimpleNamespace(get_registration_review_for_admin=AsyncMock(return_value=review))
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationCandidateConfirmAction.BACK,
        request_id=10,
        user_id=21,
        page=1,
    )

    await superadmin_registration_handlers.confirm_registration_candidate(
        callback,
        callback_data,
    )

    service.get_registration_review_for_admin.assert_awaited_once_with(
        admin_telegram_id=100,
        request_id=10,
    )
    assert inline_keyboard_texts(message.edit_text.await_args.kwargs["reply_markup"]) == [
        "Исторический 20",
        "Исторический 21",
        "↩️ Назад",
        "❌ Отмена",
    ]


async def test_registration_review_result_is_sent_to_other_superadmins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = UserView(
        id=10,
        telegram_id=200,
        display_name="Игрок Второй",
        status=UserStatus.ACTIVE,
        role=UserRole.ADMIN,
    )
    reviewer = admin_player(1, 100, UserRole.SUPERADMIN)
    other_superadmin = admin_player(2, 101, UserRole.SUPERADMIN)
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
                admins=[reviewer, other_superadmin],
            )
        ),
        list_pending_reviews_page_for_superadmin=AsyncMock(
            return_value=Page(items=[], page=0, page_size=5, total_items=0)
        ),
    )
    monkeypatch.setattr(superadmin_registration_handlers, "registration_review_service", service)
    message = SimpleNamespace(
        text="Новая заявка на регистрацию\n\nФамилия и имя: Игрок Второй",
        edit_text=AsyncMock(),
        answer=AsyncMock(),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=100, full_name="Админ 1"),
        message=message,
        bot=bot,
        answer=AsyncMock(),
    )
    callback_data = SimpleNamespace(
        action=superadmin_registrations_kb.RegistrationReviewAction.APPROVE,
        request_id=10,
        page=0,
    )

    await superadmin_registration_handlers.review_registration(callback, callback_data)

    service.approve_registration.assert_awaited_once_with(
        superadmin_telegram_id=100,
        request_id=10,
    )
    service.list_pending_reviews_page_for_superadmin.assert_awaited_once_with(
        100,
        page=0,
        page_size=5,
    )
    message.edit_text.assert_awaited_once()
    assert message.edit_text.await_args.args[0] == "Заявок на регистрацию нет."
    assert callback.answer.await_args.args[0] == "Заявка одобрена"
    assert bot.send_message.await_count == 2
    admin_call, player_call = bot.send_message.await_args_list
    assert admin_call.kwargs["chat_id"] == 101
    assert "Заявка одобрена: Админ 1" in admin_call.kwargs["text"]
    assert player_call.kwargs["chat_id"] == 200
    assert player_call.kwargs["text"] == "Ваша заявка одобрена."
    assert labels.MAIN_ADMIN not in keyboard_texts(player_call.kwargs["reply_markup"])


async def test_webhook_rejects_invalid_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhook_module, "telegram_bot", object())
    monkeypatch.setattr(webhook_module.settings, "telegram_webhook_secret", "secret")

    with pytest.raises(HTTPException) as error:
        await webhook_module.telegram_webhook(
            payload={"update_id": 1},
            x_telegram_bot_api_secret_token="wrong",
        )

    assert error.value.status_code == 403


async def test_webhook_rejects_missing_secret_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhook_module, "telegram_bot", object())
    monkeypatch.setattr(webhook_module.settings, "telegram_webhook_secret", "secret")

    with pytest.raises(HTTPException) as error:
        await webhook_module.telegram_webhook(
            payload={"update_id": 1},
            x_telegram_bot_api_secret_token=None,
        )

    assert error.value.status_code == 403


async def test_webhook_rejects_insecure_empty_configured_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(webhook_module, "telegram_bot", object())
    monkeypatch.setattr(webhook_module.settings, "telegram_webhook_secret", "")

    with pytest.raises(HTTPException) as error:
        await webhook_module.telegram_webhook(
            payload={"update_id": 1},
            x_telegram_bot_api_secret_token=None,
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


async def test_setup_webhook_requires_secret_in_public_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = SimpleNamespace(set_webhook=AsyncMock())
    monkeypatch.setattr(runtime, "telegram_bot", bot)
    monkeypatch.setattr(runtime.settings, "public_base_url", "https://gambit.example/")
    monkeypatch.setattr(runtime.settings, "telegram_webhook_secret", "")

    with pytest.raises(RuntimeError, match="TELEGRAM_WEBHOOK_SECRET"):
        await runtime.setup_telegram_webhook()

    bot.set_webhook.assert_not_called()


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


def test_telegram_runtime_uses_role_router_facades() -> None:
    assert user_handlers.router.name == "user"
    assert admin_handlers.router.name == "admin"
    assert superadmin_handlers.router.name == "superadmin"
    assert runtime.telegram_dispatcher.sub_routers == [
        superadmin_handlers.router,
        admin_handlers.router,
        user_handlers.router,
    ]
