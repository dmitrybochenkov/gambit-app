from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import format_public_weekly_schedule, format_tournament_schedule
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentParticipant,
    TournamentRegistration,
)
from app.db.models.enums import (
    RegistrationStatus,
    TournamentParticipantSource,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.services.dto import (
    TournamentRebuyView,
    WeeklyScheduleTournamentView,
    WeeklyScheduleView,
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


def test_public_weekly_schedule_formats_full_economy_and_special_rules() -> None:
    schedule = WeeklyScheduleView(
        tournaments=[
            WeeklyScheduleTournamentView(
                id=1,
                date=date(2026, 7, 22),
                tournament_type_code="bounty",
                tournament_type_name="Баунти турнир",
                description=None,
                entry_fee=600,
                entry_stack=20_000,
                addon_fee=800,
                addon_stack=125_000,
                rebuys=[
                    TournamentRebuyView(fee=600, stack=30_000),
                    TournamentRebuyView(fee=1000, stack=100_000),
                ],
                knockout_mode="small_big",
                points_multiplier=Decimal("1.00"),
                prize_place_multiplier=Decimal("1.00"),
                prize_place_multiplier_places=None,
            ),
            WeeklyScheduleTournamentView(
                id=2,
                date=date(2026, 7, 24),
                tournament_type_code="freezeout",
                tournament_type_name="Фризаут",
                description=None,
                entry_fee=1000,
                entry_stack=50_000,
                addon_fee=1000,
                addon_stack=175_000,
                rebuys=[TournamentRebuyView(fee=1000, stack=75_000)],
                knockout_mode="none",
                points_multiplier=Decimal("1.00"),
                prize_place_multiplier=Decimal("1.50"),
                prize_place_multiplier_places="[1,2]",
            ),
        ]
    )

    messages = format_public_weekly_schedule(schedule)

    assert len(messages) == 1
    assert messages[0] == (
        "🔥 РАСПИСАНИЕ ТУРНИРОВ ПОКЕРНОГО КЛУБА «ГАМБИТ»\n"
        "🔥♠️♥️♣️♦️\n\n"
        "🗓 СРЕДА — БАУНТИ ТУРНИР\n"
        "💀 Динамические нокауты\n"
        "• До финального стола — 15 очков за нокаут\n"
        "• На финальном столе — 60 очков за нокаут\n\n"
        "💰 Условия участия\n"
        "Вход: 600 ₽ — 20 000 фишек\n\n"
        "Ребаи:\n"
        "600 / 1 000 ₽\n"
        "30 000 / 100 000 фишек\n\n"
        "Аддон:\n"
        "800 ₽ — 125 000 фишек\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🗓 ПЯТНИЦА — ФРИЗАУТ\n"
        "🎯 Формат для самых скиловых игроков\n"
        "• Бесплатный напиток из перечня\n"
        "• Рейтинг за 1 и 2 место ×1.5\n\n"
        "💰 Условия участия\n"
        "Вход: 1 000 ₽ — 50 000 фишек\n"
        "Ребай: 1 000 ₽ — 75 000 фишек\n\n"
        "Аддон:\n"
        "1 000 ₽ — 175 000 фишек"
    )


def test_public_weekly_schedule_omits_empty_rebuy_and_addon_sections() -> None:
    schedule = WeeklyScheduleView(
        tournaments=[
            WeeklyScheduleTournamentView(
                id=1,
                date=date(2026, 7, 23),
                tournament_type_code="custom",
                tournament_type_name="Тестовый <турнир>",
                description="Описание *без* markdown",
                entry_fee=500,
                entry_stack=10_000,
                addon_fee=0,
                addon_stack=1,
                rebuys=[],
                knockout_mode="none",
                points_multiplier=Decimal("1.00"),
                prize_place_multiplier=Decimal("1.00"),
                prize_place_multiplier_places=None,
            )
        ]
    )

    message = format_public_weekly_schedule(schedule)[0]

    assert "🗓 ЧЕТВЕРГ — ТЕСТОВЫЙ <ТУРНИР>" in message
    assert "Описание *без* markdown" in message
    assert "Вход: 500 ₽ — 10 000 фишек" in message
    assert "Ребаи:" not in message
    assert "Ребай:" not in message
    assert "Аддон:" not in message


def test_public_weekly_schedule_splits_long_messages_on_tournament_blocks() -> None:
    schedule = WeeklyScheduleView(
        tournaments=[
            WeeklyScheduleTournamentView(
                id=index,
                date=date(2026, 7, 22),
                tournament_type_code="custom",
                tournament_type_name=f"Турнир {index}",
                description="А" * 1300,
                entry_fee=600,
                entry_stack=20_000,
                addon_fee=0,
                addon_stack=1,
                rebuys=[],
                knockout_mode="none",
                points_multiplier=Decimal("1.00"),
                prize_place_multiplier=Decimal("1.00"),
                prize_place_multiplier_places=None,
            )
            for index in range(1, 5)
        ]
    )

    messages = format_public_weekly_schedule(schedule)

    assert len(messages) > 1
    assert messages[0].startswith("🔥 РАСПИСАНИЕ")
    assert all(len(message) <= 4096 for message in messages)


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
        session.add(season)
        await session.flush()
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


async def test_admin_registration_for_today_syncs_tournament_participant(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_check_in_sync.db'}")
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
        admin_id = admin.id
        tournament_id = tournament.id
        player_id = player.id

    service = TournamentService(session_factory)
    try:
        await service.register_player_for_tournament_by_admin(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            player_id=player_id,
            from_date=date(2026, 7, 9),
        )
        await service.register_player_for_tournament_by_admin(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            player_id=player_id,
            from_date=date(2026, 7, 9),
        )

        async with session_factory() as session:
            registrations = list((await session.execute(select(TournamentRegistration))).scalars())
            participants = list((await session.execute(select(TournamentParticipant))).scalars())

        assert len(registrations) == 1
        assert registrations[0].status == RegistrationStatus.REGISTERED
        assert len(participants) == 1
        assert participants[0].tournament_id == tournament_id
        assert participants[0].user_id == player_id
        assert participants[0].source == TournamentParticipantSource.PRE_REGISTERED
        assert participants[0].checked_in_by_user_id == admin_id
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
        admin = build_player(
            telegram_id=100,
            display_name="Админ Первый",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all(
            [
                admin,
                tournament,
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
        tournament_id = tournament.id

    service = TournamentService(session_factory)
    try:
        _, players = await service.get_admin_registration_players(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            from_date=date(2026, 7, 6),
        )
        _, search_results = await service.search_admin_registration_players(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            query="анна",
            from_date=date(2026, 7, 6),
        )

        assert [player.display_name for player in players] == [
            "Анна Первая",
            "Борис Второй",
            "Яков Третий",
        ]
        assert [player.display_name for player in search_results] == ["Анна Первая"]
    finally:
        await engine.dispose()
