from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_hall_of_fame
from app.db.base import Base
from app.db.models import ScoringConfig, Season, Tournament, TournamentResult
from app.db.models.enums import TournamentStatus
from app.services.user_statistics_service import UserStatisticsService


async def test_hall_of_fame_uses_completed_seasons_and_tiebreakers(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hall.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        old_season = Season(
            name="Сезон 2025",
            scoring_config_id=config.id,
            starts_at=date(2025, 1, 1),
            ends_at=date(2025, 12, 31),
        )
        new_season = Season(
            name="Сезон 2026",
            scoring_config_id=config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 6, 30),
        )
        open_season = Season(
            name="Открытый сезон",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        viewer = build_player(telegram_id=100, display_name="Viewer")
        low_id = build_player(telegram_id=101, display_name="Иван")
        high_id = build_player(telegram_id=102, display_name="Петр")
        session.add_all([old_season, new_season, open_season, viewer, low_id, high_id])
        await session.flush()
        old_tournament = Tournament(
            season_id=old_season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2025, 5, 1),
            tournament_fund=Decimal("1000"),
            status=TournamentStatus.CLOSED,
        )
        new_tournament = Tournament(
            season_id=new_season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 5, 1),
            tournament_fund=Decimal("1000"),
            status=TournamentStatus.CLOSED,
        )
        open_tournament = Tournament(
            season_id=open_season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 1),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([old_tournament, new_tournament, open_tournament])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=old_tournament.id,
                    player_id=low_id.id,
                    tournament_points=Decimal("100"),
                    knockouts_count=1,
                    big_knockouts_count=0,
                ),
                TournamentResult(
                    tournament_id=old_tournament.id,
                    player_id=high_id.id,
                    tournament_points=Decimal("90"),
                    knockouts_count=0,
                    big_knockouts_count=1,
                ),
                TournamentResult(
                    tournament_id=new_tournament.id,
                    player_id=low_id.id,
                    tournament_points=Decimal("100"),
                    knockouts_count=2,
                    big_knockouts_count=1,
                ),
                TournamentResult(
                    tournament_id=new_tournament.id,
                    player_id=high_id.id,
                    tournament_points=Decimal("100"),
                    knockouts_count=3,
                    big_knockouts_count=0,
                ),
                TournamentResult(
                    tournament_id=open_tournament.id,
                    player_id=high_id.id,
                    tournament_points=Decimal("1000"),
                    knockouts_count=99,
                    big_knockouts_count=99,
                ),
            ]
        )
        await session.commit()

    service = UserStatisticsService(session_factory)
    try:
        seasons = await service.get_hall_of_fame(100)

        assert [season.season_name for season in seasons] == ["Сезон 2026", "Сезон 2025"]
        assert seasons[0].champion_display_name == "Иван"
        assert seasons[0].knockout_leader_display_name == "Иван"
        assert seasons[1].champion_display_name == "Иван"
        assert seasons[1].knockout_leader_display_name == "Петр"
        assert "Открытый сезон" not in format_hall_of_fame(seasons)
        assert (
            format_hall_of_fame(seasons) == "🏆 Зал славы\n\n"
            "💍 — победитель сезона\n"
            "🥊 — лучший нокаутер сезона\n\n"
            "Сезон 2026\n"
            "💍 Иван\n"
            "🥊 Иван\n\n"
            "Сезон 2025\n"
            "💍 Иван\n"
            "🥊 Петр"
        )
    finally:
        await engine.dispose()


def test_hall_of_fame_empty_state() -> None:
    assert format_hall_of_fame([]) == (
        "🏆 Зал славы\n\nПока нет завершённых сезонов с результатами."
    )
