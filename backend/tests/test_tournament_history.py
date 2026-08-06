from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_historical_tournament_result
from app.db.base import Base
from app.db.models import ScoringConfig, Season, Tournament, TournamentResult
from app.db.models.enums import TournamentStatus, UserStatus
from app.services.pagination import pagination_service
from app.services.user_statistics_service import UserStatisticsService


async def test_history_lists_only_periods_and_tournaments_with_results(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Лето 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 9, 30),
        )
        active_user = build_player(
            telegram_id=100,
            display_name="Активный игрок",
            status=UserStatus.ACTIVE,
        )
        result_user = build_player(
            telegram_id=200,
            display_name="Результат Игрок",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, active_user, result_user])
        await session.flush()
        july_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 17),
            tournament_fund=Decimal("1000"),
            status=TournamentStatus.CLOSED,
        )
        august_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 8, 3),
            tournament_fund=Decimal("1000"),
            status=TournamentStatus.CLOSED,
        )
        cancelled_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("freezeout"),
            date=date(2025, 12, 30),
            status=TournamentStatus.CANCELLED,
        )
        empty_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("double_double"),
            date=date(2024, 1, 10),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all(
            [
                july_tournament,
                august_tournament,
                cancelled_tournament,
                empty_tournament,
            ]
        )
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=july_tournament.id,
                    player_id=result_user.id,
                    place=1,
                    tournament_points=Decimal("100"),
                ),
                TournamentResult(
                    tournament_id=august_tournament.id,
                    player_id=result_user.id,
                    place=2,
                    tournament_points=Decimal("80"),
                ),
                TournamentResult(
                    tournament_id=cancelled_tournament.id,
                    player_id=result_user.id,
                    place=1,
                    tournament_points=Decimal("100"),
                ),
            ]
        )
        await session.commit()

    service = UserStatisticsService(session_factory)
    try:
        years = await service.list_history_years(100)
        months = await service.list_history_months(100, 2026)
        tournaments = await service.list_history_tournaments(100, 2026, 7)

        assert [item.year for item in years] == [2026]
        assert [(item.month, item.label) for item in months] == [
            (8, "Август"),
            (7, "Июль"),
        ]
        assert [(item.date.day, item.tournament_name) for item in tournaments] == [(17, "Классика")]
    finally:
        await engine.dispose()


async def test_history_result_sorting_and_formatter(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history_result.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Лето 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 9, 30),
        )
        viewer = build_player(telegram_id=100, display_name="Viewer")
        first = build_player(telegram_id=101, display_name="Александр Очень Длинное Имя")
        second = build_player(telegram_id=102, display_name="Борис")
        third = build_player(telegram_id=103, display_name="Виктор")
        session.add_all([season, viewer, first, second, third])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 17),
            tournament_fund=Decimal("1000"),
            status=TournamentStatus.CLOSED,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=third.id,
                    place=None,
                    knockouts_count=9,
                    big_knockouts_count=0,
                    tournament_points=Decimal("0"),
                    knockout_points=Decimal("0"),
                    bonus_points=Decimal("0"),
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=second.id,
                    place=1,
                    knockouts_count=2,
                    big_knockouts_count=2,
                    tournament_points=Decimal("7"),
                    knockout_points=Decimal("5"),
                    bonus_points=Decimal("0"),
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=first.id,
                    place=1,
                    knockouts_count=3,
                    big_knockouts_count=0,
                    tournament_points=Decimal("13"),
                    knockout_points=Decimal("0"),
                    bonus_points=Decimal("0"),
                ),
            ]
        )
        await session.commit()

    service = UserStatisticsService(session_factory)
    try:
        result = await service.get_historical_tournament_result(100, 1)

        assert [row.display_name for row in result.rows] == [
            "Борис",
            "Александр Очень Длинное Имя",
            "Виктор",
        ]
        assert [row.total_points for row in result.rows] == [
            Decimal("12.00"),
            Decimal("13.00"),
            Decimal("0.00"),
        ]
        page = pagination_service.paginate(result.rows, page=0, page_size=20)
        text = format_historical_tournament_result(result, page)
        assert "Место  Игрок                  🥊   👑🥊   Очки" in text
        assert "Борис" in text
        assert "Александр Очень Дли…" in text
        assert "—      Виктор                 9    0      0" in text
        assert "Борис                  2    2     12" in text
        assert text.startswith("⏳ История\n\n17 июля 2026\nКлассика\n\n```")
    finally:
        await engine.dispose()
