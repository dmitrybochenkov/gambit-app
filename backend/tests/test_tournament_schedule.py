from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_tournament_schedule
from app.db.base import Base
from app.db.models import Player, ScoringConfig, Season, Tournament
from app.db.models.enums import (
    PlayerStatus,
    RegistrationStatus,
    SeasonStatus,
    TournamentStatus,
)
from app.services.tournament_service import (
    TournamentAlreadyRegisteredError,
    TournamentService,
)


async def test_upcoming_schedule_uses_active_tournaments(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schedule.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 12, 31),
            status=SeasonStatus.ACTIVE,
        )
        session.add(season)
        await session.flush()
        session.add_all(
            [
                Tournament(
                    season_id=season.id,
                    type=3,
                    date=date(2026, 7, 10),
                    capacity=30,
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    type=1,
                    date=date(2026, 7, 8),
                    capacity=30,
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    type=2,
                    date=date(2026, 7, 9),
                    capacity=30,
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    type=1,
                    date=date(2026, 7, 7),
                    capacity=30,
                    status=TournamentStatus.CANCELLED,
                ),
            ]
        )
        await session.commit()

    service = TournamentService(session_factory)
    tournaments = await service.get_upcoming_schedule(from_date=date(2026, 7, 6))

    assert [tournament.type for tournament in tournaments] == [1, 2, 3]
    assert format_tournament_schedule(tournaments) == (
        "Расписание турниров\n\n"
        "Среда, 8 июля — Турнир 1 (до 30 игроков)\n"
        "Четверг, 9 июля — Турнир 2 (до 30 игроков)\n"
        "Пятница, 10 июля — Турнир 3 (до 30 игроков)"
    )
    await engine.dispose()


def test_empty_schedule_message() -> None:
    assert format_tournament_schedule([]) == "Ближайших турниров пока нет."


async def test_active_player_can_register_for_tournament(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'registration.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=date(2026, 12, 31),
            status=SeasonStatus.ACTIVE,
        )
        player = Player(
            telegram_id=100,
            full_name="Игрок Первый",
            status=PlayerStatus.ACTIVE,
        )
        session.add_all([season, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            type=1,
            date=date(2026, 7, 8),
            capacity=30,
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = TournamentService(session_factory)
    try:
        registration, registered_tournament = await service.register_player(
            telegram_id=100,
            tournament_id=tournament_id,
            from_date=date(2026, 7, 6),
        )

        assert registration.player_id == player_id
        assert registration.tournament_id == tournament_id
        assert registration.status == RegistrationStatus.REGISTERED
        assert registered_tournament.id == tournament_id

        with pytest.raises(TournamentAlreadyRegisteredError):
            await service.register_player(
                telegram_id=100,
                tournament_id=tournament_id,
                from_date=date(2026, 7, 6),
            )
    finally:
        await engine.dispose()
