from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters.statistics import rating as rating_fmt
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    SeasonHallOfFame,
    Tournament,
    TournamentResult,
)
from app.db.models.enums import TournamentStatus, UserRole, UserStatus
from app.services.dto.statistics.rating import KnockoutsRatingView, PointsRatingView
from app.services.pagination import pagination_service
from app.services.rating_service import (
    RatingFutureSeasonError,
    RatingKind,
    RatingService,
)


async def test_rating_filters_current_season_and_all_time(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rating.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        current_season = Season(
            name="Current season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        previous_season = Season(
            name="Previous season",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 6, 30),
        )
        first_player = build_player(
            telegram_id=100,
            display_name="Игрок Первый",
            status=UserStatus.ACTIVE,
        )
        second_player = build_player(
            telegram_id=200,
            display_name="King",
            status=UserStatus.ACTIVE,
        )
        zero_player = build_player(
            telegram_id=300,
            display_name="Zero",
            status=UserStatus.ACTIVE,
        )
        session.add_all(
            [
                current_season,
                previous_season,
                first_player,
                second_player,
                zero_player,
            ]
        )
        await session.flush()
        current_tournament = Tournament(
            season_id=current_season.id,
            scoring_config_id=current_season.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 8),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        previous_tournament = Tournament(
            season_id=previous_season.id,
            scoring_config_id=previous_season.scoring_config_id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 6, 20),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        active_tournament = Tournament(
            season_id=current_season.id,
            scoring_config_id=current_season.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all(
            [
                current_tournament,
                previous_tournament,
                active_tournament,
            ]
        )
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=first_player.id,
                    place=2,
                    knockouts_count=2,
                    big_knockouts_count=1,
                    tournament_points=Decimal("70"),
                    knockout_points=Decimal("20"),
                    bonus_points=10,
                ),
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=second_player.id,
                    place=1,
                    knockouts_count=4,
                    big_knockouts_count=0,
                    tournament_points=Decimal("100"),
                    knockout_points=Decimal("20"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=previous_tournament.id,
                    player_id=first_player.id,
                    place=1,
                    knockouts_count=3,
                    big_knockouts_count=0,
                    tournament_points=Decimal("50"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=zero_player.id,
                    place=3,
                    knockouts_count=0,
                    big_knockouts_count=0,
                    tournament_points=Decimal("0"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=active_tournament.id,
                    player_id=second_player.id,
                    place=1,
                    knockouts_count=99,
                    big_knockouts_count=99,
                    tournament_points=Decimal("999"),
                    knockout_points=Decimal("999"),
                    bonus_points=999,
                ),
                SeasonHallOfFame(
                    season_id=previous_season.id,
                    champion_player_id=first_player.id,
                    knockout_player_id=first_player.id,
                    updated_by_user_id=first_player.id,
                ),
            ]
        )
        await session.commit()

    service = RatingService(session_factory)
    try:
        current_rating = await service.get_rating_for_player(
            telegram_id=second_player.telegram_id,
            kind=RatingKind.CURRENT_SEASON,
        )
        all_time_rating = await service.get_rating_for_player(
            telegram_id=second_player.telegram_id,
            kind=RatingKind.ALL_TIME,
        )
        current_knockouts_rating = await service.get_rating_for_player(
            telegram_id=second_player.telegram_id,
            kind=RatingKind.KNOCKOUTS_CURRENT_SEASON,
        )
        all_time_knockouts_rating = await service.get_rating_for_player(
            telegram_id=first_player.telegram_id,
            kind=RatingKind.KNOCKOUTS_ALL_TIME,
        )
        current_title = current_rating.title
        current_points = current_rating.rows
        all_time_points = all_time_rating.rows
        current_knockouts = current_knockouts_rating.rows
        knockout_title = all_time_knockouts_rating.title
        all_time_knockouts = all_time_knockouts_rating.rows

        assert [row.display_name for row in current_points] == [
            "King",
            "Игрок Первый",
        ]
        assert [row.total_points for row in current_points] == [
            Decimal("120"),
            Decimal("100"),
        ]
        assert [row.display_name for row in all_time_points] == [
            "Игрок Первый",
            "King",
        ]
        assert [row.total_points for row in all_time_points] == [
            Decimal("150"),
            Decimal("120"),
        ]
        assert [row.display_name for row in current_knockouts] == [
            "King",
            "Игрок Первый",
        ]
        assert "Zero" not in [row.display_name for row in current_points]
        assert "Zero" not in [row.display_name for row in current_knockouts]
        assert [row.display_name for row in all_time_knockouts] == [
            "Игрок Первый",
            "King",
        ]
        assert all_time_knockouts[0].total_knockouts_count == 6
        assert all_time_knockouts[0].knockout_tournaments_count == 2
        assert all_time_knockouts[0].season_champion_titles_count == 1
        assert all_time_knockouts[0].season_knockout_leader_titles_count == 1
        current_page = pagination_service.paginate(current_points, page=0, page_size=10)
        all_time_knockouts_page = pagination_service.paginate(
            all_time_knockouts,
            page=0,
            page_size=10,
        )
        assert rating_fmt.message(
            current_title,
            current_page,
            current_player_id=second_player.id,
        ).startswith(
            "Рейтинг — текущий сезон\n💍 - победитель сезона\n"
            "🎲 - количество турниров\n\n👉 1. *King* — 120 | 🎲 1"
        )
        knockout_message = rating_fmt.message(
            knockout_title,
            all_time_knockouts_page,
            current_player_id=first_player.id,
        )
        assert (
            "Рейтинг по нокаутам — за всё время\n"
            "💥 - лучший нокаутер сезона\n"
            "🥊 - количество K.O.\n"
            "🎲 - количество турниров с нокаутами\n\n"
        ) in knockout_message
        assert "👉 1. *Игрок Первый* 💥 — 6 | 🎲 2" in knockout_message
        assert "⭐" not in knockout_message
        assert "✅" not in knockout_message
    finally:
        await engine.dispose()


async def test_rating_counts_historical_tied_places_with_authoritative_points(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tied_places_rating.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Historical season",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 3, 31),
        )
        first = build_player(telegram_id=101, display_name="First", status=UserStatus.ACTIVE)
        second = build_player(telegram_id=102, display_name="Second", status=UserStatus.ACTIVE)
        session.add_all([season, first, second])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            scoring_config_id=season.scoring_config_id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 3, 12),
            status=TournamentStatus.CLOSED,
            tournament_fund=None,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=first.id,
                    place=5,
                    tournament_points=Decimal("182.50"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=second.id,
                    place=5,
                    tournament_points=Decimal("182.50"),
                    knockout_points=Decimal("0"),
                    bonus_points=200,
                ),
            ]
        )
        await session.commit()

    service = RatingService(session_factory)
    try:
        rating = await service.get_rating_for_player(
            telegram_id=first.telegram_id,
            kind=RatingKind.ALL_TIME,
        )

        assert [(row.display_name, row.total_points) for row in rating.rows] == [
            ("Second", Decimal("382.50")),
            ("First", Decimal("182.50")),
        ]
    finally:
        await engine.dispose()


def test_points_rating_format_uses_half_up_rounding_and_current_marker() -> None:
    page = pagination_service.paginate(
        [
            PointsRatingView(
                player_id=1,
                display_name="King",
                total_points=Decimal("120.5"),
                tournaments_count=3,
                season_champion_titles_count=1,
            ),
            PointsRatingView(
                player_id=2,
                display_name="Player",
                total_points=Decimal("90.4"),
                tournaments_count=2,
            ),
        ],
        page=0,
        page_size=10,
    )

    message = rating_fmt.message("Рейтинг — за всё время", page, current_player_id=1)

    assert "⭐" not in message
    assert (
        "Рейтинг — за всё время\n"
        "💍 - победитель сезона\n"
        "🎲 - количество турниров\n\n"
        "👉 1. *King* 💍 — 121 | 🎲 3\n"
        "🥈 Player — 90 | 🎲 2"
    ) == message
    assert "✅" not in message


def test_knockout_rating_format_hides_points_and_repeats_titles() -> None:
    page = pagination_service.paginate(
        [
            KnockoutsRatingView(
                player_id=1,
                display_name="King",
                knockouts_count=4,
                big_knockouts_count=2,
                knockout_tournaments_count=2,
                season_champion_titles_count=1,
                season_knockout_leader_titles_count=2,
            )
        ],
        page=0,
        page_size=10,
    )

    message = rating_fmt.message("Рейтинг по нокаутам — за всё время", page, current_player_id=2)

    assert "⭐🥊" not in message
    assert "🥊 6" not in message
    assert (
        "Рейтинг по нокаутам — за всё время\n"
        "💥 - лучший нокаутер сезона\n"
        "🥊 - количество K.O.\n"
        "🎲 - количество турниров с нокаутами\n\n"
        "🥇 King 💥💥 — 6 | 🎲 2"
    ) == message
    assert "×2" not in message
    assert "💍" not in message


def test_points_rating_format_marks_current_player_without_honours() -> None:
    page = pagination_service.paginate(
        [
            *(
                PointsRatingView(
                    player_id=player_id,
                    display_name=f"Игрок {player_id}",
                    total_points=Decimal(2000 - player_id),
                    tournaments_count=1,
                )
                for player_id in range(1, 18)
            ),
            PointsRatingView(
                player_id=18,
                display_name="Boxing",
                total_points=Decimal("1750"),
                tournaments_count=14,
            ),
        ],
        page=17,
        page_size=1,
    )

    message = rating_fmt.message("Рейтинг — за всё время", page, current_player_id=18)

    assert "👉 18. *Boxing* — 1750 | 🎲 14" in message
    assert "✅" not in message


def test_knockout_rating_format_marks_current_player_with_ring_and_knockout_title() -> None:
    page = pagination_service.paginate(
        [
            KnockoutsRatingView(
                player_id=player_id,
                display_name=f"Игрок {player_id}",
                knockouts_count=20 - player_id,
                big_knockouts_count=0,
                knockout_tournaments_count=1,
            )
            for player_id in range(1, 5)
        ]
        + [
            KnockoutsRatingView(
                player_id=5,
                display_name="Дима",
                knockouts_count=10,
                big_knockouts_count=2,
                knockout_tournaments_count=18,
                season_champion_titles_count=1,
                season_knockout_leader_titles_count=1,
            ),
        ],
        page=4,
        page_size=1,
    )

    message = rating_fmt.message("Рейтинг по нокаутам — за всё время", page, current_player_id=5)

    assert "👉 5. *Дима* 💥 — 12 | 🎲 18" in message
    assert "✅" not in message


def test_points_rating_format_repeats_only_champion_badges() -> None:
    page = pagination_service.paginate(
        [
            PointsRatingView(
                player_id=1,
                display_name="No Titles",
                total_points=Decimal("100"),
                tournaments_count=3,
            ),
            PointsRatingView(
                player_id=2,
                display_name="One Champion",
                total_points=Decimal("90"),
                tournaments_count=3,
                season_champion_titles_count=1,
            ),
            PointsRatingView(
                player_id=3,
                display_name="Two Champions",
                total_points=Decimal("80"),
                tournaments_count=3,
                season_champion_titles_count=2,
            ),
            PointsRatingView(
                player_id=4,
                display_name="Three Champions",
                total_points=Decimal("70"),
                tournaments_count=3,
                season_champion_titles_count=3,
            ),
        ],
        page=0,
        page_size=10,
    )

    message = rating_fmt.message("Рейтинг — за всё время", page, current_player_id=99)

    assert "🥇 No Titles — 100 | 🎲 3" in message
    assert "🥈 One Champion 💍 — 90 | 🎲 3" in message
    assert "🥉 Two Champions 💍💍 — 80 | 🎲 3" in message
    assert "4. Three Champions 💍💍💍 — 70 | 🎲 3" in message
    assert "💥" not in message
    assert "x2" not in message
    assert "×2" not in message
    assert "(2)" not in message


def test_knockout_rating_format_repeats_only_knockout_title_badges() -> None:
    page = pagination_service.paginate(
        [
            KnockoutsRatingView(
                player_id=1,
                display_name="No Titles",
                knockouts_count=10,
                big_knockouts_count=0,
                knockout_tournaments_count=3,
            ),
            KnockoutsRatingView(
                player_id=2,
                display_name="One Knockout Title",
                knockouts_count=9,
                big_knockouts_count=0,
                knockout_tournaments_count=3,
                season_knockout_leader_titles_count=1,
            ),
            KnockoutsRatingView(
                player_id=3,
                display_name="Two Knockout Titles",
                knockouts_count=8,
                big_knockouts_count=0,
                knockout_tournaments_count=3,
                season_knockout_leader_titles_count=2,
            ),
            KnockoutsRatingView(
                player_id=4,
                display_name="Three Knockout Titles",
                knockouts_count=7,
                big_knockouts_count=0,
                knockout_tournaments_count=3,
                season_champion_titles_count=3,
                season_knockout_leader_titles_count=3,
            ),
        ],
        page=0,
        page_size=10,
    )

    message = rating_fmt.message("Рейтинг по нокаутам — за всё время", page, current_player_id=99)

    assert "🥇 No Titles — 10 | 🎲 3" in message
    assert "🥈 One Knockout Title 💥 — 9 | 🎲 3" in message
    assert "🥉 Two Knockout Titles 💥💥 — 8 | 🎲 3" in message
    assert "4. Three Knockout Titles 💥💥💥 — 7 | 🎲 3" in message
    assert "💍" not in message
    assert "🥊 - количество K.O." in message
    assert "x2" not in message
    assert "×2" not in message
    assert "(2)" not in message


async def test_rating_badges_are_specific_to_rating_kind(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rating_badges.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        completed = Season(
            name="Completed",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 3, 31),
        )
        current = Season(
            name="Current",
            scoring_config_id=config.id,
            starts_at=date(2026, 4, 1),
            ends_at=None,
        )
        player = build_player(
            telegram_id=100,
            display_name="Title Collector",
            status=UserStatus.ACTIVE,
        )
        session.add_all([completed, current, player])
        await session.flush()
        tournament = Tournament(
            season_id=completed.id,
            scoring_config_id=completed.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 1, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    place=1,
                    knockouts_count=1,
                    big_knockouts_count=0,
                    tournament_points=Decimal("100"),
                    knockout_points=Decimal("10"),
                    bonus_points=0,
                ),
                SeasonHallOfFame(
                    season_id=completed.id,
                    champion_player_id=player.id,
                    knockout_player_id=player.id,
                    updated_by_user_id=player.id,
                ),
            ]
        )
        await session.commit()

    service = RatingService(session_factory)
    try:
        points_rating = await service.get_rating_for_player(
            telegram_id=100,
            kind=RatingKind.ALL_TIME,
            today=date(2026, 4, 2),
        )
        knockout_rating = await service.get_rating_for_player(
            telegram_id=100,
            kind=RatingKind.KNOCKOUTS_ALL_TIME,
            today=date(2026, 4, 2),
        )

        points_message = rating_fmt.message(
            points_rating.title,
            pagination_service.paginate(points_rating.rows, page=0, page_size=10),
            current_player_id=999,
        )
        knockout_message = rating_fmt.message(
            knockout_rating.title,
            pagination_service.paginate(knockout_rating.rows, page=0, page_size=10),
            current_player_id=999,
        )

        assert "Title Collector 💍 — 110 | 🎲 1" in points_message
        assert "💥" not in points_message
        assert "Title Collector 💥 — 1 | 🎲 1" in knockout_message
        assert "💍" not in knockout_message
    finally:
        await engine.dispose()


def test_points_rating_format_repeats_champion_badges_without_counter_suffix() -> None:
    page = pagination_service.paginate(
        [
            PointsRatingView(
                player_id=1,
                display_name="Mixed",
                total_points=Decimal("100"),
                tournaments_count=3,
                season_champion_titles_count=2,
            ),
        ],
        page=0,
        page_size=10,
    )

    message = rating_fmt.message("Рейтинг — за всё время", page, current_player_id=99)

    assert "🥇 Mixed 💍💍 — 100 | 🎲 3" in message
    assert "×2" not in message


async def test_active_superadmin_can_open_rating_after_new_session(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'superadmin_rating.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            build_player(
                telegram_id=100,
                display_name="Дима Боченков",
                status=UserStatus.ACTIVE,
                role=UserRole.SUPERADMIN,
            )
        )
        await session.commit()

    service = RatingService(session_factory)
    try:
        rating = await service.get_rating_for_player(
            telegram_id=100,
            kind=RatingKind.ALL_TIME,
        )

        assert rating.title == "Рейтинг — за всё время"
        assert rating.rows == []
    finally:
        await engine.dispose()


async def test_knockout_games_count_and_completed_season_title_tiebreakers(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rating_titles.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        completed = Season(
            name="Completed",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 3, 31),
        )
        current = Season(
            name="Current",
            scoring_config_id=config.id,
            starts_at=date(2026, 4, 1),
            ends_at=None,
        )
        low_id_player = build_player(
            telegram_id=100,
            display_name="Low Id",
            status=UserStatus.ACTIVE,
        )
        high_id_player = build_player(
            telegram_id=200,
            display_name="High Id",
            status=UserStatus.ACTIVE,
        )
        zero_knockouts_player = build_player(
            telegram_id=300,
            display_name="Zero KO",
            status=UserStatus.ACTIVE,
        )
        session.add_all([completed, current, low_id_player, high_id_player, zero_knockouts_player])
        await session.flush()
        tournaments = [
            Tournament(
                season_id=completed.id,
                scoring_config_id=completed.scoring_config_id,
                tournament_type_id=tournament_type_id("bounty"),
                date=date(2026, 1, 1 + index),
                status=TournamentStatus.CLOSED,
                tournament_fund=1000,
            )
            for index in range(4)
        ]
        current_tournament = Tournament(
            season_id=current.id,
            scoring_config_id=current.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 4, 2),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([*tournaments, current_tournament])
        await session.flush()

        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournaments[0].id,
                    player_id=low_id_player.id,
                    place=1,
                    knockouts_count=2,
                    big_knockouts_count=0,
                    tournament_points=Decimal("100"),
                    knockout_points=Decimal("0"),
                    bonus_points=20,
                ),
                TournamentResult(
                    tournament_id=tournaments[1].id,
                    player_id=low_id_player.id,
                    place=None,
                    knockouts_count=0,
                    big_knockouts_count=0,
                    tournament_points=Decimal("0"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=tournaments[2].id,
                    player_id=low_id_player.id,
                    place=None,
                    knockouts_count=0,
                    big_knockouts_count=1,
                    tournament_points=Decimal("0"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=tournaments[3].id,
                    player_id=low_id_player.id,
                    place=None,
                    knockouts_count=0,
                    big_knockouts_count=0,
                    tournament_points=Decimal("0"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=tournaments[0].id,
                    player_id=high_id_player.id,
                    place=2,
                    knockouts_count=3,
                    big_knockouts_count=0,
                    tournament_points=Decimal("120"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=tournaments[0].id,
                    player_id=zero_knockouts_player.id,
                    place=None,
                    knockouts_count=0,
                    big_knockouts_count=0,
                    tournament_points=Decimal("0"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=high_id_player.id,
                    place=1,
                    knockouts_count=10,
                    big_knockouts_count=0,
                    tournament_points=Decimal("500"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                SeasonHallOfFame(
                    season_id=completed.id,
                    champion_player_id=low_id_player.id,
                    knockout_player_id=low_id_player.id,
                    updated_by_user_id=low_id_player.id,
                ),
            ]
        )
        await session.commit()

    service = RatingService(session_factory)
    try:
        knockout_rating = await service.get_rating_for_player(
            telegram_id=low_id_player.telegram_id,
            kind=RatingKind.KNOCKOUTS_ALL_TIME,
            today=date(2026, 7, 29),
        )
        points_rating = await service.get_rating_for_player(
            telegram_id=low_id_player.telegram_id,
            kind=RatingKind.ALL_TIME,
            today=date(2026, 7, 29),
        )

        low_id_knockouts = next(
            row for row in knockout_rating.rows if row.player_id == low_id_player.id
        )
        high_id_knockouts = next(
            row for row in knockout_rating.rows if row.player_id == high_id_player.id
        )
        low_id_points = next(row for row in points_rating.rows if row.player_id == low_id_player.id)
        high_id_points = next(
            row for row in points_rating.rows if row.player_id == high_id_player.id
        )

        assert low_id_knockouts.total_knockouts_count == 3
        assert low_id_knockouts.knockout_tournaments_count == 2
        assert low_id_knockouts.season_knockout_leader_titles_count == 1
        assert high_id_knockouts.season_knockout_leader_titles_count == 0
        assert low_id_points.season_champion_titles_count == 1
        assert high_id_points.season_champion_titles_count == 0
    finally:
        await engine.dispose()


async def test_rating_current_season_uses_season_covering_supplied_date(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rating_transition.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        old_season = Season(
            name="Old season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 8, 9),
        )
        future_season = Season(
            name="Future season",
            scoring_config_id=config.id,
            starts_at=date(2026, 8, 10),
            ends_at=None,
        )
        player = build_player(
            telegram_id=100,
            display_name="Игрок Первый",
            status=UserStatus.ACTIVE,
        )
        session.add_all([old_season, future_season, player])
        await session.flush()
        old_tournament = Tournament(
            season_id=old_season.id,
            scoring_config_id=old_season.scoring_config_id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 9),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        future_tournament = Tournament(
            season_id=future_season.id,
            scoring_config_id=future_season.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 8, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([old_tournament, future_tournament])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=old_tournament.id,
                    player_id=player.id,
                    place=1,
                    knockouts_count=1,
                    big_knockouts_count=0,
                    tournament_points=Decimal("100"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
                TournamentResult(
                    tournament_id=future_tournament.id,
                    player_id=player.id,
                    place=1,
                    knockouts_count=2,
                    big_knockouts_count=0,
                    tournament_points=Decimal("200"),
                    knockout_points=Decimal("0"),
                    bonus_points=0,
                ),
            ]
        )
        await session.commit()

    service = RatingService(session_factory)
    try:
        before_transition = await service.get_rating_for_player(
            telegram_id=100,
            kind=RatingKind.CURRENT_SEASON,
            today=date(2026, 8, 9),
        )
        on_transition = await service.get_rating_for_player(
            telegram_id=100,
            kind=RatingKind.CURRENT_SEASON,
            today=date(2026, 8, 10),
        )

        assert [row.total_points for row in before_transition.rows] == [Decimal("100")]
        assert [row.total_points for row in on_transition.rows] == [Decimal("200")]
    finally:
        await engine.dispose()


async def test_rating_current_season_returns_empty_when_no_season_covers_today(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rating_no_season.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            build_player(
                telegram_id=100,
                display_name="Игрок Первый",
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()

    service = RatingService(session_factory)
    try:
        rating = await service.get_rating_for_player(
            telegram_id=100,
            kind=RatingKind.CURRENT_SEASON,
            today=date(2026, 8, 9),
        )

        assert rating.title == "Рейтинг — текущий сезон"
        assert rating.rows == []
    finally:
        await engine.dispose()


async def test_rating_selected_season_and_season_picker_exclude_future(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rating_selected.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        hidden = Season(
            name="Сезон 1",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 3, 31),
            is_statistics_visible=False,
        )
        completed = Season(
            name="Весна 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 4, 1),
            ends_at=date(2026, 6, 30),
        )
        current = Season(
            name="Лето 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 8, 31),
        )
        future = Season(
            name="Осень 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 9, 1),
            ends_at=None,
        )
        player = build_player(telegram_id=100, display_name="Игрок")
        session.add_all([hidden, completed, current, future, player])
        await session.flush()
        hidden_tournament = Tournament(
            season_id=hidden.id,
            scoring_config_id=hidden.scoring_config_id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 1, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        completed_tournament = Tournament(
            season_id=completed.id,
            scoring_config_id=completed.scoring_config_id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 4, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        current_tournament = Tournament(
            season_id=current.id,
            scoring_config_id=current.scoring_config_id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 10),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([hidden_tournament, completed_tournament, current_tournament])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=hidden_tournament.id,
                    player_id=player.id,
                    tournament_points=Decimal("50"),
                ),
                TournamentResult(
                    tournament_id=completed_tournament.id,
                    player_id=player.id,
                    tournament_points=Decimal("100"),
                ),
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=player.id,
                    tournament_points=Decimal("200"),
                ),
            ]
        )
        await session.commit()
        completed_id = completed.id
        future_id = future.id

    service = RatingService(session_factory)
    try:
        seasons = await service.list_rating_seasons(100, today=date(2026, 8, 10))
        rating = await service.get_rating_for_player(
            100,
            RatingKind.SELECTED_SEASON,
            season_id=completed_id,
            today=date(2026, 8, 10),
        )
        all_time_rating = await service.get_rating_for_player(
            100,
            RatingKind.ALL_TIME,
            today=date(2026, 8, 10),
        )

        assert [season.name for season in seasons] == ["Лето 2026", "Весна 2026"]
        assert rating.title == "Рейтинг — Весна 2026"
        assert [row.total_points for row in rating.rows] == [Decimal("100")]
        assert [row.total_points for row in all_time_rating.rows] == [Decimal("350")]
        with pytest.raises(RatingFutureSeasonError):
            await service.get_rating_for_player(
                100,
                RatingKind.SELECTED_SEASON,
                season_id=future_id,
                today=date(2026, 8, 10),
            )
    finally:
        await engine.dispose()
