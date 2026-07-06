from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_profile
from app.db.base import Base
from app.db.models import (
    Player,
    ScoringConfig,
    Season,
    Tournament,
    TournamentResult,
)
from app.db.models.enums import PlayerStatus, SeasonStatus, TournamentStatus
from app.services.profile_service import ProfileKind, ProfileService


async def test_profile_filters_current_season_and_all_time(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
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
        player = Player(
            telegram_id=100,
            full_name="Игрок Первый",
            nickname="Ace",
            status=PlayerStatus.ACTIVE,
        )
        player_without_results = Player(
            telegram_id=200,
            nickname="King",
            status=PlayerStatus.ACTIVE,
        )
        session.add_all(
            [
                current_season,
                previous_season,
                player,
                player_without_results,
            ]
        )
        await session.flush()
        current_tournament = Tournament(
            season_id=current_season.id,
            type=1,
            date=date(2026, 7, 8),
            capacity=30,
            status=TournamentStatus.ACTIVE,
        )
        previous_tournament = Tournament(
            season_id=previous_season.id,
            type=2,
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
                    player_id=player.id,
                    place=2,
                    knockouts_count=2,
                    boss_knockouts_count=1,
                    tournament_points=Decimal("70"),
                    knockout_points=Decimal("20"),
                    bonus_points=Decimal("10"),
                ),
                TournamentResult(
                    tournament_id=previous_tournament.id,
                    player_id=player.id,
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

    service = ProfileService(session_factory)
    try:
        current_title, current_stats = await service.get_profile(
            telegram_id=100,
            kind=ProfileKind.CURRENT_SEASON,
        )
        all_time_title, all_time_stats = await service.get_profile(
            telegram_id=100,
            kind=ProfileKind.ALL_TIME,
        )
        _, empty_stats = await service.get_profile(
            telegram_id=200,
            kind=ProfileKind.CURRENT_SEASON,
        )

        assert current_title == "Твой профиль — текущий сезон"
        assert current_stats is not None
        assert current_stats.display_name == "Игрок Первый (Ace)"
        assert current_stats.total_points == Decimal("100")
        assert current_stats.total_knockouts_count == 3
        assert current_stats.tournaments_count == 1
        assert current_stats.first_places_count == 0
        assert current_stats.second_places_count == 1

        assert all_time_title == "Твой профиль — за всё время"
        assert all_time_stats is not None
        assert all_time_stats.total_points == Decimal("150")
        assert all_time_stats.total_knockouts_count == 6
        assert all_time_stats.tournaments_count == 2
        assert all_time_stats.first_places_count == 1
        assert all_time_stats.second_places_count == 1

        assert empty_stats is not None
        assert empty_stats.display_name == "King"
        assert empty_stats.total_points == Decimal("0")
        assert empty_stats.tournaments_count == 0
        assert "Количество призовых мест:" in format_profile(
            all_time_title,
            all_time_stats,
        )
    finally:
        await engine.dispose()
