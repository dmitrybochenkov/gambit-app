from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_rating
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentResult,
)
from app.db.models.enums import SeasonStatus, TournamentStatus, UserStatus
from app.services.pagination import pagination_service
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
                    player_id=first_player.id,
                    place=2,
                    knockouts_count=2,
                    big_knockouts_count=1,
                    tournament_points=Decimal("70"),
                    knockout_points=Decimal("20"),
                    bonus_points=Decimal("10"),
                ),
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=second_player.id,
                    place=1,
                    knockouts_count=4,
                    big_knockouts_count=0,
                    tournament_points=Decimal("100"),
                    knockout_points=Decimal("20"),
                    bonus_points=Decimal("0"),
                ),
                TournamentResult(
                    tournament_id=previous_tournament.id,
                    player_id=first_player.id,
                    place=1,
                    knockouts_count=3,
                    big_knockouts_count=0,
                    tournament_points=Decimal("50"),
                    knockout_points=Decimal("0"),
                    bonus_points=Decimal("0"),
                ),
                TournamentResult(
                    tournament_id=current_tournament.id,
                    player_id=zero_player.id,
                    place=3,
                    knockouts_count=0,
                    big_knockouts_count=0,
                    tournament_points=Decimal("0"),
                    knockout_points=Decimal("0"),
                    bonus_points=Decimal("0"),
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
        assert all_time_knockouts[0].knockout_points == Decimal("20")
        assert all_time_knockouts[0].tournaments_count == 2
        current_page = pagination_service.paginate(current_points, page=0, page_size=10)
        all_time_knockouts_page = pagination_service.paginate(
            all_time_knockouts,
            page=0,
            page_size=10,
        )
        assert format_rating(
            current_title,
            current_page,
            current_player_id=second_player.id,
        ).startswith(
            "Рейтинг — текущий сезон\n"
            "⭐ - количество очков\n"
            "🎲 - количество турниров\n\n"
            "🥇 *King* — ⭐120 | 🎲 1"
        )
        knockout_message = format_rating(
            knockout_title,
            all_time_knockouts_page,
            current_player_id=first_player.id,
        )
        assert (
            "Рейтинг по нокаутам — за всё время\n"
            "🥊 - количество нокаутов\n"
            "⭐🥊 - количество очков за нокауты\n"
            "🎲 - количество турниров\n\n"
        ) in knockout_message
        assert "🥊 6 | ⭐🥊 20 | 🎲 2" in knockout_message
    finally:
        await engine.dispose()
