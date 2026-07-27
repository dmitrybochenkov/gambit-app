from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_profile
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentResult,
)
from app.db.models.enums import SeasonStatus, TournamentStatus, UserStatus
from app.services.dto import PlayerProfileView
from app.services.profile_service import ProfileKind, ProfileService


def test_profile_formats_only_non_zero_prize_places() -> None:
    message = format_profile(
        "Твой профиль — за всё время",
        PlayerProfileView(
            display_name="Дима Боченков",
            total_points=Decimal("0"),
            knockout_points=Decimal("0"),
            knockouts_count=0,
            big_knockouts_count=0,
            tournaments_count=0,
            first_places_count=3,
            second_places_count=0,
            third_places_count=5,
            fourth_places_count=0,
            fifth_places_count=4,
        ),
    )

    assert message == (
        "Твой профиль — за всё время\n"
        "⭐ - количество очков\n"
        "🥊 - количество нокаутов\n"
        "⭐🥊 - количество очков за нокауты\n"
        "🎲 - количество турниров\n\n"
        "Дима Боченков\n"
        "⭐ 0 | 🥊 0 | ⭐🥊 0 | 🎲 0\n\n"
        "Количество призовых мест:\n"
        "🥇 x3\n"
        "🥉 x5\n"
        "5️⃣ x4"
    )


async def test_profile_filters_current_season_and_all_time(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile.db'}")
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
        player = build_player(
            telegram_id=100,
            display_name="Игрок Первый",
            status=UserStatus.ACTIVE,
        )
        player_without_results = build_player(
            telegram_id=200,
            display_name="King",
            status=UserStatus.ACTIVE,
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
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 8),
            status=TournamentStatus.ACTIVE,
        )
        previous_tournament = Tournament(
            season_id=previous_season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 6, 20),
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
                    big_knockouts_count=1,
                    tournament_points=Decimal("70"),
                    knockout_points=Decimal("20"),
                    bonus_points=Decimal("10"),
                ),
                TournamentResult(
                    tournament_id=previous_tournament.id,
                    player_id=player.id,
                    place=1,
                    knockouts_count=3,
                    big_knockouts_count=0,
                    tournament_points=Decimal("50"),
                    knockout_points=Decimal("0"),
                    bonus_points=Decimal("0"),
                ),
            ]
        )
        await session.commit()

    service = ProfileService(session_factory)
    try:
        current_title, current_stats = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.CURRENT_SEASON,
        )
        all_time_title, all_time_stats = await service.get_profile_for_player(
            telegram_id=100,
            kind=ProfileKind.ALL_TIME,
        )
        _, empty_stats = await service.get_profile_for_player(
            telegram_id=200,
            kind=ProfileKind.CURRENT_SEASON,
        )

        assert current_title == "Твой профиль — текущий сезон"
        assert current_stats is not None
        assert current_stats.display_name == "Игрок Первый"
        assert current_stats.total_points == Decimal("100")
        assert current_stats.knockout_points == Decimal("20")
        assert current_stats.total_knockouts_count == 3
        assert current_stats.tournaments_count == 1
        assert current_stats.first_places_count == 0
        assert current_stats.second_places_count == 1

        assert all_time_title == "Твой профиль — за всё время"
        assert all_time_stats is not None
        assert all_time_stats.total_points == Decimal("150")
        assert all_time_stats.knockout_points == Decimal("20")
        assert all_time_stats.total_knockouts_count == 6
        assert all_time_stats.tournaments_count == 2
        assert all_time_stats.first_places_count == 1
        assert all_time_stats.second_places_count == 1

        assert empty_stats is not None
        assert empty_stats.display_name == "King"
        assert empty_stats.total_points == Decimal("0")
        assert empty_stats.knockout_points == Decimal("0")
        assert empty_stats.tournaments_count == 0
        all_time_message = format_profile(
            all_time_title,
            all_time_stats,
        )
        empty_message = format_profile("Твой профиль — текущий сезон", empty_stats)
        assert "Количество призовых мест:" in all_time_message
        assert "🥇 x1" in all_time_message
        assert "🥈 x1" in all_time_message
        assert "🥉" not in all_time_message
        assert "4️⃣" not in all_time_message
        assert "5️⃣" not in all_time_message
        assert "Количество призовых мест:" not in empty_message
    finally:
        await engine.dispose()
