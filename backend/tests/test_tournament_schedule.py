from datetime import date
from pathlib import Path

from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_tournament_schedule
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentRegistration,
)
from app.db.models.enums import (
    RegistrationStatus,
    TournamentStatus,
    UserRole,
    UserStatus,
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
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        session.add(season)
        await session.flush()
        session.add_all(
            [
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("freezeout"),
                    date=date(2026, 7, 10),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("bounty"),
                    date=date(2026, 7, 8),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("classic"),
                    date=date(2026, 7, 9),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("bounty"),
                    date=date(2026, 7, 7),
                    status=TournamentStatus.CANCELLED,
                ),
            ]
        )
        await session.commit()

    service = TournamentService(session_factory)
    tournaments = await service.get_upcoming_schedule(from_date=date(2026, 7, 6))

    assert [tournament.tournament_type_id for tournament in tournaments] == [
        tournament_type_id("bounty"),
        tournament_type_id("classic"),
        tournament_type_id("freezeout"),
    ]
    assert format_tournament_schedule(tournaments) == (
        "Расписание турниров\n\n"
        "• Среда, 8 июля — Баунти турнир\n"
        "• Четверг, 9 июля — Классика\n"
        "• Пятница, 10 июля — Фризаут"
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
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        player = build_player(
            telegram_id=100,
            display_name="Игрок Первый",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, player])
        await session.flush()
        tournaments = [
            Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("bounty"),
                date=date(2026, 7, 8),
                status=TournamentStatus.ACTIVE,
            ),
            Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 7, 9),
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
            registration.status == RegistrationStatus.REGISTERED for registration in registrations
        )

        upcoming_registrations = await service.get_player_upcoming_registrations(
            telegram_id=100,
            from_date=date(2026, 7, 6),
        )
        assert [tournament.id for tournament in upcoming_registrations] == tournament_ids
        assert [tournament.tournament_type_name for tournament in upcoming_registrations] == [
            "Баунти турнир",
            "Классика",
        ]

        cancelled_tournaments = await service.cancel_player_tournament_registrations(
            telegram_id=100,
            tournament_ids=tournament_ids,
            from_date=date(2026, 7, 6),
        )
        assert [tournament.id for tournament in cancelled_tournaments] == tournament_ids
        assert [tournament.tournament_type_name for tournament in cancelled_tournaments] == [
            "Баунти турнир",
            "Классика",
        ]

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
            registration.cancelled_at is not None for registration in cancelled_registrations
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


async def test_active_superadmin_can_use_player_tournament_flows_after_new_session(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'superadmin_flow.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        player = build_player(
            telegram_id=100,
            display_name="Дима Боченков",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        session.add_all([season, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = TournamentService(session_factory)
    try:
        schedule = await service.get_schedule_for_player(
            telegram_id=100,
            from_date=date(2026, 7, 6),
        )
        options = await service.get_registration_options_for_player(
            telegram_id=100,
            from_date=date(2026, 7, 6),
        )
        registered = await service.register_player_for_tournaments(
            telegram_id=100,
            tournament_ids=[tournament_id],
            from_date=date(2026, 7, 6),
        )

        assert [tournament.id for tournament in schedule] == [tournament_id]
        assert [tournament.id for tournament in options] == [tournament_id]
        assert [tournament.id for tournament in registered] == [tournament_id]

        async with session_factory() as session:
            stored_registration = await session.scalar(
                select(TournamentRegistration).where(
                    TournamentRegistration.tournament_id == tournament_id,
                    TournamentRegistration.player_id == player_id,
                )
            )
        assert stored_registration is not None
        assert stored_registration.status == RegistrationStatus.REGISTERED

        upcoming_registrations = await service.get_player_upcoming_registrations(
            telegram_id=100,
            from_date=date(2026, 7, 6),
        )
        cancelled = await service.cancel_player_tournament_registrations(
            telegram_id=100,
            tournament_ids=[tournament_id],
            from_date=date(2026, 7, 6),
        )

        assert [tournament.id for tournament in upcoming_registrations] == [tournament_id]
        assert [tournament.id for tournament in cancelled] == [tournament_id]
    finally:
        await engine.dispose()


async def test_admin_can_register_player_for_tournament(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_registration.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        admin = build_player(
            telegram_id=100,
            display_name="Админ Первый",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        player = build_player(
            telegram_id=101,
            display_name="Игрок Первый",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, admin, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = TournamentService(session_factory)
    try:
        tournament_view, user_view = await service.register_player_for_tournament_by_admin(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            player_id=player_id,
            from_date=date(2026, 7, 6),
        )
        await service.register_player_for_tournament_by_admin(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            player_id=player_id,
            from_date=date(2026, 7, 6),
        )

        assert tournament_view.id == tournament_id
        assert tournament_view.tournament_type_name == "Классика"
        assert user_view.id == player_id
        async with session_factory() as session:
            registrations = list(
                (
                    await session.execute(
                        select(TournamentRegistration).where(
                            TournamentRegistration.tournament_id == tournament_id,
                            TournamentRegistration.player_id == player_id,
                        )
                    )
                ).scalars()
            )
        assert len(registrations) == 1
        assert registrations[0].status == RegistrationStatus.REGISTERED
    finally:
        await engine.dispose()


async def test_admin_player_registration_list_is_sorted_and_searchable(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'player_search.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        admin = build_player(
            telegram_id=100,
            display_name="Админ Первый",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        session.add_all(
            [
                admin,
                build_player(
                    telegram_id=101,
                    display_name="Яков Третий",
                    status=UserStatus.ACTIVE,
                ),
                build_player(
                    telegram_id=102,
                    display_name="Анна Первая",
                    status=UserStatus.ACTIVE,
                ),
                build_player(
                    telegram_id=103,
                    display_name="Борис Второй",
                    status=UserStatus.ACTIVE,
                ),
            ]
        )
        await session.commit()

    service = TournamentService(session_factory)
    try:
        players = await service.list_players_for_admin_registration(100)
        search_results = await service.search_players_for_admin_registration(
            admin_telegram_id=100,
            query="анна",
        )

        assert [player.display_name for player in players] == [
            "Анна Первая",
            "Борис Второй",
            "Яков Третий",
        ]
        assert [player.display_name for player in search_results] == ["Анна Первая"]
    finally:
        await engine.dispose()
