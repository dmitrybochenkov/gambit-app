from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_tournament_schedule
from app.db.base import Base
from app.db.models import (
    Player,
    ScoringConfig,
    Season,
    Tournament,
    TournamentRegistration,
)
from app.db.models.enums import (
    PlayerStatus,
    RegistrationStatus,
    SeasonStatus,
    TournamentStatus,
)
from app.services.tournament_service import TournamentService


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


async def test_active_player_can_register_for_multiple_tournaments(tmp_path: Path) -> None:
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
        tournaments = [
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
        ]
        session.add_all(tournaments)
        await session.commit()
        tournament_ids = [tournament.id for tournament in tournaments]
        player_id = player.id

    service = TournamentService(session_factory)
    try:
        registered_tournaments = await service.register_player_for_tournaments(
            telegram_id=100,
            tournament_ids=tournament_ids,
            from_date=date(2026, 7, 6),
        )

        assert [tournament.id for tournament in registered_tournaments] == tournament_ids

        await service.register_player_for_tournaments(
            telegram_id=100,
            tournament_ids=tournament_ids,
            from_date=date(2026, 7, 6),
        )

        async with session_factory() as session:
            registrations = list(
                (
                    await session.execute(
                        select(TournamentRegistration).order_by(
                            TournamentRegistration.tournament_id
                        )
                    )
                ).scalars()
            )
        assert len(registrations) == 2
        assert all(registration.player_id == player_id for registration in registrations)
        assert all(
            registration.status == RegistrationStatus.REGISTERED
            for registration in registrations
        )

        upcoming_registrations = await service.get_player_upcoming_registrations(
            telegram_id=100,
            from_date=date(2026, 7, 6),
        )
        assert [
            tournament.id for tournament in upcoming_registrations
        ] == tournament_ids

        cancelled_tournaments = (
            await service.cancel_player_tournament_registrations(
                telegram_id=100,
                tournament_ids=tournament_ids,
                from_date=date(2026, 7, 6),
            )
        )
        assert [
            tournament.id for tournament in cancelled_tournaments
        ] == tournament_ids

        async with session_factory() as session:
            cancelled_registrations = list(
                (
                    await session.execute(
                        select(TournamentRegistration).order_by(
                            TournamentRegistration.tournament_id
                        )
                    )
                ).scalars()
            )
        assert all(
            registration.status == RegistrationStatus.CANCELLED
            for registration in cancelled_registrations
        )
        assert all(
            registration.cancelled_at is not None
            for registration in cancelled_registrations
        )
        assert (
            await service.get_player_upcoming_registrations(
                telegram_id=100,
                from_date=date(2026, 7, 6),
            )
            == []
        )
    finally:
        await engine.dispose()
