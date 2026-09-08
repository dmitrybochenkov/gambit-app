from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import (
    TOURNAMENT_TYPE_SHORT_NAMES,
    build_player,
    seed_tournament_types_async,
    tournament_type_id,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import results as result_fmt
from app.bot.telegram.formatters.statistics import history as history_fmt
from app.db.base import Base
from app.db.models import ScoringConfig, Season, Tournament, TournamentResult, TournamentType
from app.db.models.enums import TournamentStatus, UserStatus
from app.services.dto.statistics.history import (
    HistoricalTournamentResultRowView,
    HistoricalTournamentResultView,
    HistoricalTournamentView,
)
from app.services.pagination import pagination_service
from app.services.user_statistics_service import (
    HistoricalTournamentNotFoundError,
    UserStatisticsService,
)


def test_history_formats_points_as_rounded_integer() -> None:
    result = HistoricalTournamentResultView(
        tournament=HistoricalTournamentView(
            id=1,
            date=date(2026, 3, 15),
            display_name="Классика",
        ),
        rows=[
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="Игрок",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
                total_points=Decimal("88.5"),
            )
        ],
    )
    page = pagination_service.paginate(result.rows, page=0, page_size=20)

    text = history_fmt.tournament_result(result, page)

    assert "   89" in text
    assert "88.5" not in text


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
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 17),
            tournament_fund=1000,
            status=TournamentStatus.CLOSED,
        )
        august_tournament = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 8, 3),
            tournament_fund=1000,
            status=TournamentStatus.CLOSED,
        )
        empty_tournament = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("double_double"),
            date=date(2024, 1, 10),
            status=TournamentStatus.ACTIVE,
        )
        active_with_result_tournament = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 9, 1),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all(
            [
                july_tournament,
                august_tournament,
                empty_tournament,
                active_with_result_tournament,
            ]
        )
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=july_tournament.id,
                    player_id=result_user.id,
                    place=2,
                    tournament_points=Decimal("100"),
                ),
                TournamentResult(
                    tournament_id=august_tournament.id,
                    player_id=result_user.id,
                    place=2,
                    tournament_points=Decimal("80"),
                ),
                TournamentResult(
                    tournament_id=active_with_result_tournament.id,
                    player_id=result_user.id,
                    place=1,
                    tournament_points=Decimal("999"),
                ),
            ]
        )
        await session.commit()

    service = UserStatisticsService(session_factory)
    try:
        years = await service.list_history_years(100)
        months = await service.list_history_months(100, 2026)
        tournaments = await service.list_history_tournaments(100, 2026, 7)
        with pytest.raises(HistoricalTournamentNotFoundError):
            await service.get_historical_tournament_result(
                100,
                active_with_result_tournament.id,
            )

        assert [item.year for item in years] == [2026]
        assert [(item.month, item.label) for item in months] == [
            (7, "Июль"),
            (8, "Август"),
        ]
        assert [(item.date.day, item.display_name) for item in tournaments] == [(17, "Classic")]
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("row", "present_headers", "absent_headers"),
    [
        (
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="Игрок",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
                bonus_points=0,
                total_points=Decimal("10"),
            ),
            ["№", "Игрок", "Очки"],
            [" КО", "БКО", "Бонус"],
        ),
        (
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="Игрок",
                place=1,
                knockouts_count=2,
                big_knockouts_count=0,
                bonus_points=0,
                total_points=Decimal("10"),
            ),
            ["№", "Игрок", "КО", "Очки"],
            ["БКО", "Бонус"],
        ),
        (
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="Игрок",
                place=1,
                knockouts_count=0,
                big_knockouts_count=1,
                bonus_points=0,
                total_points=Decimal("10"),
            ),
            ["№", "Игрок", "БКО", "Очки"],
            [" КО", "Бонус"],
        ),
        (
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="Игрок",
                place=1,
                knockouts_count=0,
                big_knockouts_count=0,
                bonus_points=3,
                total_points=Decimal("10"),
            ),
            ["№", "Игрок", "Бонус", "Очки"],
            [" КО", "БКО"],
        ),
    ],
)
def test_history_result_table_uses_dynamic_columns(
    row: HistoricalTournamentResultRowView,
    present_headers: list[str],
    absent_headers: list[str],
) -> None:
    result = HistoricalTournamentResultView(
        tournament=HistoricalTournamentView(
            id=1,
            date=date(2026, 7, 17),
            display_name="Классика",
        ),
        rows=[row],
    )
    page = pagination_service.paginate(result.rows, page=0, page_size=20)

    text = history_fmt.tournament_result(result, page)

    header = text.split("```", maxsplit=2)[1].splitlines()[1]
    for present_header in present_headers:
        assert present_header in header
    for absent_header in absent_headers:
        assert absent_header not in header


def test_history_table_uses_35_character_budget_and_21_character_name_cap() -> None:
    result = HistoricalTournamentResultView(
        tournament=HistoricalTournamentView(
            id=1,
            date=date(2026, 7, 17),
            display_name="Классика",
        ),
        rows=[
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="ABCDEFGHIJKLMNOPQRSTU",
                place=1,
                knockouts_count=4,
                big_knockouts_count=1,
                total_points=Decimal("795"),
            )
        ],
    )
    page = pagination_service.paginate(result.rows, page=0, page_size=20)

    text = history_fmt.tournament_result(result, page)
    table_lines = text.split("```", maxsplit=2)[1].strip("\n").splitlines()

    assert history_fmt.MAX_TABLE_WIDTH == 35
    assert history_fmt.MAX_PLAYER_NAME_WIDTH == 21
    assert table_lines[0] == "№ Игрок                 КО БКО Очки"
    assert "ABCDEFGHIJKLMNOPQRSTU" in table_lines[1]
    assert all(len(line) <= history_fmt.MAX_TABLE_WIDTH for line in table_lines)


def test_history_table_shrinks_and_stays_separate_from_results_table() -> None:
    result = HistoricalTournamentResultView(
        tournament=HistoricalTournamentView(
            id=1,
            date=date(2026, 7, 17),
            display_name="Классика",
        ),
        rows=[
            HistoricalTournamentResultRowView(
                player_id=1,
                display_name="Сос",
                place=None,
                knockouts_count=2,
                big_knockouts_count=0,
                total_points=Decimal("30"),
            )
        ],
    )
    page = pagination_service.paginate(result.rows, page=0, page_size=20)

    text = history_fmt.tournament_result(result, page)
    table_lines = text.split("```", maxsplit=2)[1].strip("\n").splitlines()

    assert result_fmt._game_table_lines is not history_fmt._table_lines
    assert table_lines[0] == "№ Игрок КО Очки"
    assert table_lines[1] == "— Сос    2   30"
    assert all(len(line) <= history_fmt.MAX_TABLE_WIDTH for line in table_lines)


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
        tied = build_player(telegram_id=104, display_name="Глеб")
        session.add_all([season, viewer, first, second, third, tied])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 17),
            tournament_fund=1000,
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
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=second.id,
                    place=1,
                    knockouts_count=2,
                    big_knockouts_count=2,
                    tournament_points=Decimal("7"),
                    knockout_points=Decimal("5"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=first.id,
                    place=2,
                    knockouts_count=3,
                    big_knockouts_count=0,
                    tournament_points=Decimal("13"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=tied.id,
                    place=2,
                    knockouts_count=1,
                    big_knockouts_count=0,
                    tournament_points=Decimal("4"),
                    knockout_points=Decimal("0"),
                    bonus_points=6,
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
            "Глеб",
            "Виктор",
        ]
        assert [row.total_points for row in result.rows] == [
            Decimal("12.00"),
            Decimal("13.00"),
            Decimal("10.00"),
            Decimal("0.00"),
        ]
        page = pagination_service.paginate(result.rows, page=0, page_size=20)
        text = history_fmt.tournament_result(result, page)
        table_lines = text.split("```", maxsplit=2)[1].strip("\n").splitlines()
        assert table_lines[0] == "№ Игрок           КО БКО Бонус Очки"
        assert "Борис" in text
        assert "Александр Очен…" in text
        assert "— Виктор           9   0     0    0" in text
        assert "Борис            2   2     0   12" in text
        assert "Глеб             1   0     6   10" in text
        assert all(len(line) <= history_fmt.MAX_TABLE_WIDTH for line in table_lines)
        assert text.startswith("⏳ История\n\n17 июля 2026\nКлассика\n\n```")
    finally:
        await engine.dispose()


async def test_history_chronological_order_and_legacy_display_names(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history_legacy.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        legacy_type = TournamentType(
            id=100,
            code="legacy_unknown",
            name="Неопределенный турнир",
            short_name="Турнир",
        )
        classic_type = TournamentType(
            id=101,
            code="classic",
            name="Классика",
            short_name="Classic",
        )
        season = Season(
            name="История",
            scoring_config_id=config.id,
            starts_at=date(2025, 1, 1),
            ends_at=None,
        )
        viewer = build_player(telegram_id=100, display_name="Viewer")
        player = build_player(telegram_id=101, display_name="Player")
        session.add_all([legacy_type, classic_type, season, viewer, player])
        await session.flush()
        first = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=legacy_type.id,
            date=date(2025, 12, 30),
            status=TournamentStatus.CLOSED,
            tournament_fund=None,
        )
        second = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=legacy_type.id,
            date=date(2026, 1, 2),
            status=TournamentStatus.CLOSED,
            tournament_fund=None,
        )
        third = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=classic_type.id,
            date=date(2026, 1, 5),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([first, second, third])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=first.id,
                    player_id=player.id,
                    tournament_points=Decimal("10"),
                ),
                TournamentResult(
                    tournament_id=second.id,
                    player_id=player.id,
                    knockouts_count=1,
                    tournament_points=Decimal("20"),
                ),
                TournamentResult(
                    tournament_id=third.id,
                    player_id=player.id,
                    tournament_points=Decimal("30"),
                ),
            ]
        )
        await session.commit()

    service = UserStatisticsService(session_factory)
    try:
        years = await service.list_history_years(100)
        months = await service.list_history_months(100, 2026)
        tournaments = await service.list_history_tournaments(100, 2026, 1)
        first_result = await service.get_historical_tournament_result(100, first.id)
        second_result = await service.get_historical_tournament_result(100, second.id)

        assert [item.year for item in years] == [2025, 2026]
        assert [(item.month, item.label) for item in months] == [(1, "Январь")]
        assert [(item.date.day, item.display_name) for item in tournaments] == [
            (2, "Bounty"),
            (5, "Classic"),
        ]
        assert first_result.tournament.display_name == "Турнир"
        assert second_result.tournament.display_name == "Bounty"
    finally:
        await engine.dispose()


async def test_history_tournament_list_uses_short_names_for_real_types(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history_short_names.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="История",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=None,
        )
        viewer = build_player(telegram_id=100, display_name="Viewer")
        player = build_player(telegram_id=101, display_name="Player")
        session.add_all([season, viewer, player])
        await session.flush()

        type_codes = tuple(TOURNAMENT_TYPE_SHORT_NAMES)
        tournaments = [
            Tournament(
                season_id=season.id,
                scoring_config_id=season.scoring_config_id,
                tournament_type_id=tournament_type_id(code),
                date=date(2026, 1, day),
                status=TournamentStatus.CLOSED,
                tournament_fund=1000,
            )
            for day, code in enumerate(type_codes, start=1)
        ]
        session.add_all(tournaments)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    tournament_points=Decimal("10"),
                )
                for tournament in tournaments
            ]
        )
        await session.commit()

    service = UserStatisticsService(session_factory)
    try:
        history_tournaments = await service.list_history_tournaments(100, 2026, 1)

        assert [item.display_name for item in history_tournaments] == [
            TOURNAMENT_TYPE_SHORT_NAMES[code] for code in type_codes
        ]
    finally:
        await engine.dispose()
