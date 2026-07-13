from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import seed_tournament_types_async, tournament_type_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_rating
from app.db.base import Base
from app.db.models import (
    Player,
    ScoringConfig,
    Season,
    Tournament,
    TournamentResult,
)
from app.db.models.enums import PlayerStatus, SeasonStatus, TournamentStatus
from app.services.rating_service import RatingKind, RatingService


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
            ends_at=date(2026, 12, 31),
            status=SeasonStatus.ACTIVE,
        )
        previous_season = Season(
            name="Previous season",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 6, 30),
            status=SeasonStatus.CLOSED,
        )
        first_player = Player(
            telegram_id=100,
            full_name="Игрок Первый",
            nickname="Ace",
            status=PlayerStatus.ACTIVE,
        )
        second_player = Player(
            telegram_id=200,
            nickname="King",
            status=PlayerStatus.ACTIVE,
        )
        session.add_all(
            [
                current_season,
                previous_season,
                first_player,
                second_player,
            ]
        )
        await session.flush()
        current_tournament = Tournament(
            season_id=current_season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 8),
            capacity=30,
            status=TournamentStatus.ACTIVE,
        )
        previous_tournament = Tournament(
            season_id=previous_season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 6, 20),
            capacity=30,
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([current_tournament, previous_tournament])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=first_player.id,
                    place=2,
                    knockouts_count=2,
                    boss_knockouts_count=1,
                    tournament_points=Decimal("70"),
                    knockout_points=Decimal("20"),
                    bonus_points=Decimal("10"),
                ),
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=second_player.id,
                    place=1,
                    knockouts_count=4,
                    boss_knockouts_count=0,
                    tournament_points=Decimal("100"),
                    knockout_points=Decimal("20"),
                    bonus_points=Decimal("0"),
                ),
                TournamentResult(
                    tournament_id=previous_tournament.id,
                    player_id=first_player.id,
                    place=1,
                    knockouts_count=3,
                    boss_knockouts_count=0,
                    tournament_points=Decimal("50"),
                    knockout_points=Decimal("0"),
                    bonus_points=Decimal("0"),
                ),
            ]
        )
        await session.commit()

    service = RatingService(session_factory)
    try:
        current_title, current_points = await service.get_rating(
            RatingKind.CURRENT_SEASON
        )
        all_time_title, all_time_points = await service.get_rating(
            RatingKind.ALL_TIME
        )
        _, current_knockouts = await service.get_rating(
            RatingKind.KNOCKOUTS_CURRENT_SEASON
        )
        knockout_title, all_time_knockouts = await service.get_rating(
            RatingKind.KNOCKOUTS_ALL_TIME
        )

        assert [row.display_name for row in current_points] == [
            "King",
            "Игрок Первый (Ace)",
        ]
        assert [row.total_points for row in current_points] == [
            Decimal("120"),
            Decimal("100"),
        ]
        assert [row.display_name for row in all_time_points] == [
            "Игрок Первый (Ace)",
            "King",
        ]
        assert [row.total_points for row in all_time_points] == [
            Decimal("150"),
            Decimal("120"),
        ]
        assert [row.display_name for row in current_knockouts] == [
            "King",
            "Игрок Первый (Ace)",
        ]
        assert [row.display_name for row in all_time_knockouts] == [
            "Игрок Первый (Ace)",
            "King",
        ]
        assert all_time_knockouts[0].total_knockouts_count == 6
        assert format_rating(current_title, current_points).startswith(
            "Рейтинг — текущий сезон\n\n1. King — 120 очков"
        )
        assert "всего КО: 6, Босс КО: 1" in format_rating(
            knockout_title,
            all_time_knockouts,
        )
    finally:
        await engine.dispose()
