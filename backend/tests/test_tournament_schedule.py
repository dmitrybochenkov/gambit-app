from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import (
    build_player,
    seed_tournament_types_async,
    tournament_type_id,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.telegram.formatters import schedules as schedule_fmt
from app.bot.telegram.formatters import tournaments as tournament_fmt
from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    RegistrationRequest,
    ScoringConfig,
    Season,
    Tournament,
    TournamentEconomyConfig,
    TournamentRebuyConfig,
    TournamentRegistration,
    TournamentResult,
    TournamentType,
    TournamentTypeRule,
)
from app.db.models.enums import (
    KnockoutMode,
    TournamentResultSource,
    TournamentStatus,
    TournamentTypeStatus,
    UserRole,
    UserStatus,
)
from app.services.dto.schedules import (
    TournamentRebuyView,
    WeeklyScheduleTournamentView,
    WeeklyScheduleView,
)
from app.services.tournament_check_in_service import (
    TournamentCheckInClosedError,
    TournamentCheckInService,
)
from app.services.tournament_service import (
    TournamentRegistrationAlreadyCheckedInError,
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
    assert tournament_fmt.schedule(tournaments) == (
        "Расписание турниров\n\n"
        "Нажми на кнопку турнира, про который хочешь узнать более подробную информацию."
    )
    await engine.dispose()


def test_empty_schedule_message() -> None:
    assert tournament_fmt.schedule([]) == "Расписание турниров\n\nТурниров пока нет."


async def test_schedule_tournament_details_are_db_driven(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schedule_detail.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        tournament_type = TournamentType(
            id=100,
            code="test_db_driven",
            name="Тестовый DB-турнир",
            short_name="Test DB",
            description="Уникальное описание из базы",
            status=TournamentTypeStatus.ACTIVE,
        )
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 7, 1),
            ends_at=None,
        )
        user = build_player(
            telegram_id=123,
            display_name="Игрок",
            status=UserStatus.ACTIVE,
        )
        session.add_all([tournament_type, season, user])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type.id,
            date=date(2026, 8, 22),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all(
            [
                tournament,
                TournamentEconomyConfig(
                    tournament_type_id=tournament_type.id,
                    entry_fee=1234,
                    entry_stack=56_789,
                    addon_fee=2345,
                    addon_stack=67_890,
                ),
                TournamentRebuyConfig(
                    tournament_type_id=tournament_type.id,
                    rebuy_order=1,
                    fee=3456,
                    stack=78_901,
                ),
                TournamentTypeRule(
                    tournament_type_id=tournament_type.id,
                    points_multiplier=Decimal("1.25"),
                    prize_place_multiplier=Decimal("1.50"),
                    prize_place_multiplier_places="[1, 3]",
                    knockout_mode=KnockoutMode.SMALL_BIG,
                    supports_bonus_points=True,
                ),
            ]
        )
        await session.commit()
        tournament_id = tournament.id

    service = TournamentService(session_factory, clock=FixedClock(datetime(2026, 8, 1)))
    try:
        details = await service.get_schedule_tournament_details_for_player(123, tournament_id)
        text = tournament_fmt.schedule_detail(details)

        assert details.tournament_type_name == "Тестовый DB-турнир"
        assert details.description == "Уникальное описание из базы"
        assert "Суббота, 22 августа — Тестовый DB-турнир" in text
        assert "Уникальное описание из базы" in text
        assert "Вход: 1 234 ₽ — 56 789 фишек" in text
        assert "Ребай: 3 456 ₽ — 78 901 фишек" in text
        assert "2 345 ₽ — 67 890 фишек" in text
        assert "Множитель рейтинга: ×1.25" in text
        assert "Множитель призовых мест: ×1.5 (1, 3)" in text
        assert "Нокауты: КО и БКО" in text
        assert "Бонусные очки" in text
    finally:
        await engine.dispose()


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

    messages = schedule_fmt.public_weekly(schedule)

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

    message = schedule_fmt.public_weekly(schedule)[0]

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

    messages = schedule_fmt.public_weekly(schedule)

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
                date=date(2026, 7, 31),
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
                (await session.execute(select(TournamentRegistration))).scalars()
            )
        assert cancelled_registrations == []
        assert (
            await service.get_player_upcoming_registrations(
                telegram_id=100,
                from_date=date(2026, 7, 6),
            )
            == []
        )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.SUPERADMIN])
async def test_active_admin_roles_can_use_player_tournament_flows_after_new_session(
    tmp_path: Path,
    role: UserRole,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / f'{role.value}_flow.db'}")
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
            role=role,
        )
        session.add_all([season, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 31),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(
            TournamentRegistration(
                tournament_id=tournament.id,
                player_id=player.id,
            )
        )
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


async def test_check_in_registered_player_creates_result_without_new_registration(
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
        await session.flush()
        session.add(
            TournamentRegistration(
                tournament_id=tournament.id,
                player_id=player.id,
            )
        )
        await session.commit()
        admin_user_id = admin.id
        tournament_id = tournament.id
        player_id = player.id

    check_in_service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        first = await check_in_service.check_in_registered(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            user_id=player_id,
        )
        second = await check_in_service.check_in_registered(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            user_id=player_id,
        )

        async with session_factory() as session:
            registrations = list((await session.execute(select(TournamentRegistration))).scalars())
            results = list((await session.execute(select(TournamentResult))).scalars())

        assert first.created is True
        assert second.created is False
        assert len(registrations) == 1
        assert len(results) == 1
        assert results[0].tournament_id == tournament_id
        assert results[0].player_id == player_id
        assert results[0].source == TournamentResultSource.REGISTERED
        assert results[0].checked_in_by_user_id == admin_user_id
    finally:
        await engine.dispose()


async def test_check_in_uses_tournament_day_before_start_hour(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'check_in_boundary.db'}")
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
        previous_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        current_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("freezeout"),
            date=date(2026, 7, 10),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([previous_tournament, current_tournament])
        await session.flush()
        session.add(
            TournamentRegistration(
                tournament_id=previous_tournament.id,
                player_id=player.id,
            )
        )
        await session.commit()
        previous_tournament_id = previous_tournament.id
        current_tournament_id = current_tournament.id
        player_id = player.id

    before_start = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 10, 5, tzinfo=ZoneInfo("Europe/Moscow"))),
        tournament_day_start_hour=11,
    )
    at_start = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 10, 11, tzinfo=ZoneInfo("Europe/Moscow"))),
        tournament_day_start_hour=11,
    )
    try:
        today_before_start = await before_start.list_today_tournaments(100)
        today_at_start = await at_start.list_today_tournaments(100)
        check_in = await before_start.check_in_registered(
            admin_telegram_id=100,
            tournament_id=previous_tournament_id,
            user_id=player_id,
        )

        assert [tournament.id for tournament in today_before_start] == [previous_tournament_id]
        assert [tournament.id for tournament in today_at_start] == [current_tournament_id]
        assert check_in.tournament.id == previous_tournament_id
        assert check_in.created is True
    finally:
        await engine.dispose()


async def test_admin_cannot_check_in_previous_open_tournament_after_business_day(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_late_check_in.db'}")
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
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        player = build_player(telegram_id=101, display_name="Player", status=UserStatus.ACTIVE)
        session.add_all([season, admin, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(TournamentRegistration(tournament_id=tournament.id, player_id=player.id))
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 10, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        with pytest.raises(TournamentCheckInClosedError):
            await service.check_in_registered(
                admin_telegram_id=100,
                tournament_id=tournament_id,
                user_id=player_id,
            )
    finally:
        await engine.dispose()


async def test_superadmin_can_check_in_previous_open_tournament_with_late_hint(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'superadmin_late_check_in.db'}")
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
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        player = build_player(telegram_id=101, display_name="Player", status=UserStatus.ACTIVE)
        session.add_all([season, superadmin, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(TournamentRegistration(tournament_id=tournament.id, player_id=player.id))
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 10, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        tournaments = await service.list_today_tournaments(100)
        view = await service.get_check_in(100, tournament_id)
        result = await service.check_in_registered(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            user_id=player_id,
        )

        assert [tournament.id for tournament in tournaments] == [tournament_id]
        assert view.is_superadmin_late_override is True
        assert result.created is True
    finally:
        await engine.dispose()


async def test_cannot_cancel_tournament_registration_after_check_in(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cancel_after_check_in.db'}")
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
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([admin, player, tournament])
        await session.flush()
        session.add(TournamentRegistration(tournament_id=tournament.id, player_id=player.id))
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    check_in_service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    tournament_service = TournamentService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        await check_in_service.check_in_registered(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            user_id=player_id,
        )

        with pytest.raises(TournamentRegistrationAlreadyCheckedInError):
            await tournament_service.cancel_player_tournament_registrations(
                telegram_id=101,
                tournament_ids=[tournament_id],
                from_date=date(2026, 7, 9),
            )

        async with session_factory() as session:
            registration = await session.scalar(select(TournamentRegistration))
            result = await session.scalar(select(TournamentResult))

        assert registration is not None
        assert result is not None
    finally:
        await engine.dispose()


async def test_check_in_new_offline_player_creates_active_user_without_review(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'new_offline_check_in.db'}")
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
        session.add_all([admin, tournament])
        await session.commit()
        admin_user_id = admin.id
        tournament_id = tournament.id

    check_in_service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        result = await check_in_service.create_user_and_check_in(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            display_name="Новый Игрок",
        )

        async with session_factory() as session:
            requests = list((await session.execute(select(RegistrationRequest))).scalars())
            stored_results = list((await session.execute(select(TournamentResult))).scalars())

        assert result.created is True
        assert result.user.telegram_id is None
        assert result.user.status.value == UserStatus.ACTIVE.value
        assert result.user.role.value == UserRole.PLAYER.value
        assert requests == []
        assert len(stored_results) == 1
        assert stored_results[0].source == TournamentResultSource.WALK_IN_NEW
        assert stored_results[0].checked_in_by_user_id == admin_user_id
    finally:
        await engine.dispose()


async def test_check_in_new_player_similarity_search_does_not_mutate_database(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'new_player_search.db'}")
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
        existing = build_player(
            telegram_id=None,
            display_name="Дима Большой",
            status=UserStatus.ACTIVE,
        )
        session.add_all([admin, tournament, existing])
        await session.commit()
        tournament_id = tournament.id

    check_in_service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        _, candidates, exact_exists = await check_in_service.find_new_player_candidates(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            display_name="Дима  Большой",
        )

        async with session_factory() as session:
            requests = list((await session.execute(select(RegistrationRequest))).scalars())
            stored_results = list((await session.execute(select(TournamentResult))).scalars())

        assert exact_exists is True
        assert [candidate.display_name for candidate in candidates] == ["Дима Большой"]
        assert requests == []
        assert stored_results == []
    finally:
        await engine.dispose()


async def test_check_in_existing_player_search_is_sorted_and_excludes_checked_in(
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

    check_in_service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        search_results = await check_in_service.search_users(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            query="анна",
        )
        await check_in_service.check_in_existing_user(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            user_id=search_results[0].id,
        )
        after_check_in = await check_in_service.search_users(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            query="анна",
        )

        assert [player.display_name for player in search_results] == ["Анна Первая"]
        assert after_check_in == []
    finally:
        await engine.dispose()


async def test_check_in_existing_user_search_includes_admin_roles(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_player_search.db'}")
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
        operator = build_player(
            telegram_id=100,
            display_name="Оператор",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        admin_player = build_player(
            telegram_id=101,
            display_name="Админ Игрок",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        superadmin_player = build_player(
            telegram_id=102,
            display_name="Супер Игрок",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        blocked_player = build_player(
            telegram_id=103,
            display_name="Блок Игрок",
            status=UserStatus.BLOCKED,
        )
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all(
            [
                operator,
                admin_player,
                superadmin_player,
                blocked_player,
                tournament,
            ]
        )
        await session.commit()
        tournament_id = tournament.id

    check_in_service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        search_results = await check_in_service.search_users(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            query="игрок",
        )

        assert [user.display_name for user in search_results] == [
            "Админ Игрок",
            "Супер Игрок",
        ]
    finally:
        await engine.dispose()


async def test_check_in_summary_counters_use_sources_and_include_admin_players(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'check_in_counters.db'}")
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
        operator = build_player(
            telegram_id=100,
            display_name="Оператор",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        admin_registered = build_player(
            telegram_id=101,
            display_name="Админ Игрок",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        superadmin_registered = build_player(
            telegram_id=102,
            display_name="Супер Игрок",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        walk_in_existing = build_player(
            telegram_id=103,
            display_name="Гость Из Базы",
            status=UserStatus.ACTIVE,
        )
        walk_in_new = build_player(
            telegram_id=None,
            display_name="Офлайн Новичок",
            status=UserStatus.ACTIVE,
        )
        session.add_all(
            [
                season,
                operator,
                admin_registered,
                superadmin_registered,
                walk_in_existing,
                walk_in_new,
            ]
        )
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 9),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=admin_registered.id,
                ),
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=superadmin_registered.id,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=admin_registered.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_at=datetime(2026, 7, 9, 12, 3, tzinfo=ZoneInfo("Europe/Moscow")),
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=walk_in_existing.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_at=datetime(2026, 7, 9, 12, 1, tzinfo=ZoneInfo("Europe/Moscow")),
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=walk_in_new.id,
                    source=TournamentResultSource.WALK_IN_NEW,
                    checked_in_at=datetime(2026, 7, 9, 12, 2, tzinfo=ZoneInfo("Europe/Moscow")),
                ),
            ]
        )
        await session.commit()
        tournament_id = tournament.id

    check_in_service = TournamentCheckInService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 9, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        view = await check_in_service.get_check_in(
            admin_telegram_id=100,
            tournament_id=tournament_id,
        )
        checked_in_players = await check_in_service.get_checked_in_players(
            admin_telegram_id=100,
            tournament_id=tournament_id,
        )

        assert view.registered_count == 2
        assert view.registered_checked_in_count == 1
        assert view.walk_in_count == 2
        assert view.checked_in_count == 3
        assert view.checked_in_count == view.registered_checked_in_count + view.walk_in_count
        assert view.checked_in_count == checked_in_players.total_count
        assert [player.display_name for player in checked_in_players.players] == [
            "Гость Из Базы",
            "Офлайн Новичок",
            "Админ Игрок",
        ]
    finally:
        await engine.dispose()
