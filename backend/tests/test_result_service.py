from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import build_player, seed_tournament_types_async, tournament_type_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentPhoto,
    TournamentRegistration,
    TournamentResult,
    TournamentTypeRule,
)
from app.db.models.enums import (
    KnockoutMode,
    TournamentResultSource,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.services.result_fields import ResultField
from app.services.result_service import (
    FutureTournamentCannotBeClosedError,
    ResultDuplicateNameError,
    ResultInvalidFundError,
    ResultInvalidPlayerDataError,
    ResultService,
    ResultTodayTournamentNotFoundError,
)


@pytest.mark.parametrize("fund", [None, 0, -10, 105, Decimal("10.5")])
def test_live_close_fund_validation_rejects_invalid_values(fund: object) -> None:
    with pytest.raises(ResultInvalidFundError):
        ResultService.validate_tournament_fund(fund)  # type: ignore[arg-type]


def test_live_close_fund_validation_accepts_valid_value() -> None:
    assert ResultService.validate_tournament_fund(1000) == 1000


async def test_today_result_entry_uses_only_today_active_tournament(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'open_results.db'}")
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
        session.add_all([season, admin])
        await session.flush()
        session.add_all(
            [
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("classic"),
                    date=date(2026, 7, 19),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("freezeout"),
                    date=date(2026, 7, 20),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("double_double"),
                    date=date(2026, 7, 18),
                    tournament_fund=1000,
                    status=TournamentStatus.CLOSED,
                ),
            ]
        )
        await session.commit()

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    results = await service.get_today_tournament_results(100)

    assert results.tournament.date == date(2026, 7, 20)
    assert results.tournament.tournament_type_name == "Фризаут"
    await engine.dispose()


async def test_today_result_entry_rejects_when_today_has_no_active_tournament(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'no_today_results.db'}")
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
        session.add_all([season, admin])
        await session.flush()
        session.add_all(
            [
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("classic"),
                    date=date(2026, 7, 19),
                    status=TournamentStatus.ACTIVE,
                ),
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("freezeout"),
                    date=date(2026, 7, 20),
                    tournament_fund=1000,
                    status=TournamentStatus.CLOSED,
                ),
            ]
        )
        await session.commit()

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    with pytest.raises(ResultTodayTournamentNotFoundError):
        await service.get_today_tournament_results(100)
    await engine.dispose()


async def test_result_rows_are_edited_directly_and_close_tournament(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'results.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig(
            place_1_coefficient=Decimal("0.40"),
            place_5_coefficient=Decimal("0.10"),
            knockout_small_points=20,
            knockout_big_points=75,
        )
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        session.add(
            TournamentTypeRule(
                tournament_type_id=tournament_type_id("boss_bounty"),
                knockout_mode=KnockoutMode.SMALL_BIG,
            )
        )
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
            role=UserRole.SUPERADMIN,
        )
        players = [
            build_player(
                telegram_id=telegram_id,
                display_name=f"Player {telegram_id}",
                status=UserStatus.ACTIVE,
            )
            for telegram_id in range(101, 106)
        ]
        session.add_all([season, admin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("boss_bounty"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=admin.id,
                )
                for player in players
            ]
        )
        session.add(
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="file-1",
                telegram_file_unique_id="unique-1",
                uploaded_by_user_id=admin.id,
                position=0,
            )
        )
        await session.commit()
        tournament_id = tournament.id
        player_ids = [player.id for player in players]

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 18, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    results = await service.get_tournament_results(100, tournament_id)

    assert not hasattr(results, "checked_in_count")
    assert results.knockout_mode == KnockoutMode.SMALL_BIG.value
    assert [player.player_id for player in results.players] == player_ids
    assert await service.validate_results(100, tournament_id) == [
        "Введи места: 1, 2, 3, 4, 5.",
        "Введи хотя бы один 🥊 или 👑🥊.",
    ]

    await service.update_player_result_field(
        100, tournament_id, player_ids[0], ResultField.PLACE, 1
    )
    await service.update_player_result_field(
        100, tournament_id, player_ids[0], ResultField.KNOCKOUTS, 2
    )
    await service.update_player_result_field(
        100, tournament_id, player_ids[0], ResultField.BIG_KNOCKOUTS, 1
    )
    await service.update_player_result_field(
        100, tournament_id, player_ids[1], ResultField.PLACE, 2
    )
    await service.update_player_result_field(
        100, tournament_id, player_ids[1], ResultField.KNOCKOUTS, 1
    )
    for place, player_id in zip(range(3, 6), player_ids[2:], strict=True):
        await service.update_player_result_field(
            100, tournament_id, player_id, ResultField.PLACE, place
        )
    closed = await service.close_tournament(100, tournament_id, 1000)

    assert closed.tournament_fund == 1000
    async with session_factory() as session:
        stored_results = list(
            (
                await session.execute(select(TournamentResult).order_by(TournamentResult.player_id))
            ).scalars()
        )
        tournament = await session.get(Tournament, tournament_id)

    assert tournament is not None
    assert tournament.status == TournamentStatus.CLOSED
    assert len(stored_results) == 5
    assert stored_results[0].tournament_points == Decimal("400.00")
    assert stored_results[0].knockout_points == Decimal("115.00")
    assert stored_results[1].tournament_points == Decimal("250.00")
    assert stored_results[1].knockout_points == Decimal("20.00")
    await engine.dispose()


async def test_closeable_tournaments_use_business_date_and_status(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'closeable_results.db'}")
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
        players = [
            build_player(
                telegram_id=101 + index,
                display_name=f"Player {index + 1}",
                status=UserStatus.ACTIVE,
            )
            for index in range(5)
        ]
        session.add_all([season, superadmin, *players])
        await session.flush()
        not_ready_active = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 17),
            status=TournamentStatus.ACTIVE,
        )
        old_active = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        today_active = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 20),
            status=TournamentStatus.ACTIVE,
        )
        future_active = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("freezeout"),
            date=date(2026, 7, 21),
            status=TournamentStatus.ACTIVE,
        )
        closed = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("double_double"),
            date=date(2026, 7, 19),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add_all([not_ready_active, old_active, today_active, future_active, closed])
        await session.flush()
        for tournament in [old_active, today_active]:
            session.add_all(
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=superadmin.id,
                    place=index,
                )
                for index, player in enumerate(players, start=1)
            )
        await session.commit()
        old_active_id = old_active.id
        today_active_id = today_active.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    closeable = await service.list_unclosed_tournaments_for_superadmin(100)

    assert [item.tournament.id for item in closeable] == [
        today_active_id,
        old_active_id,
        not_ready_active.id,
    ]
    assert closeable[0].reasons == ["Фото не добавлены."]
    assert closeable[-1].reasons == ["Турнир ещё не начался.", "Фото не добавлены."]
    await engine.dispose()


async def test_mystery_bounty_uses_places_and_bonus_without_knockouts(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mystery_results.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig(
            place_1_coefficient=Decimal("0.40"),
            place_2_coefficient=Decimal("0.25"),
            place_3_coefficient=Decimal("0.15"),
            place_4_coefficient=Decimal("0.10"),
            place_5_coefficient=Decimal("0.10"),
        )
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        session.add(
            TournamentTypeRule(
                tournament_type_id=tournament_type_id("mystery_bounty"),
                knockout_mode=KnockoutMode.NONE,
                supports_bonus_points=True,
            )
        )
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
        players = [
            build_player(
                telegram_id=101 + index,
                display_name=f"Player {index + 1}",
                status=UserStatus.ACTIVE,
            )
            for index in range(5)
        ]
        session.add_all([season, superadmin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("mystery_bounty"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=superadmin.id,
                )
                for player in players
            ]
        )
        session.add(
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="mystery-file-1",
                telegram_file_unique_id="mystery-unique-1",
                uploaded_by_user_id=superadmin.id,
                position=0,
            )
        )
        await session.commit()
        tournament_id = tournament.id
        player_ids = [player.id for player in players]

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 18, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    results = await service.get_tournament_results(100, tournament_id)

    assert results.knockout_mode == KnockoutMode.NONE.value
    assert results.supports_bonus_points is True
    assert ResultService.editable_result_fields(results) == [ResultField.PLACE, ResultField.BONUS]
    assert await service.validate_results(100, tournament_id) == ["Введи места: 1, 2, 3, 4, 5."]

    for place, player_id in zip(range(1, 6), player_ids, strict=True):
        await service.update_player_result_field(
            100,
            tournament_id,
            player_id,
            ResultField.PLACE,
            place,
        )
    await service.update_player_result_field(
        100,
        tournament_id,
        player_ids[0],
        ResultField.BONUS,
        12,
    )
    closed = await service.close_tournament(100, tournament_id, 1000)

    player = ResultService.find_result_player(closed, player_ids[0])
    assert player is not None
    assert player.tournament_points == Decimal("400.00")
    assert player.knockout_points == Decimal("0.00")
    assert player.total_points == Decimal("412.00")
    await engine.dispose()


async def test_add_existing_player_to_past_tournament_creates_zero_result(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'past_add_existing.db'}")
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
        player = build_player(telegram_id=101, display_name="Past Player")
        session.add_all([season, admin, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    results = await service.add_existing_player_to_tournament(100, tournament_id, player_id)

    assert [player.display_name for player in results.players] == ["Past Player"]
    async with session_factory() as session:
        stored = (
            await session.execute(
                select(TournamentResult).where(TournamentResult.tournament_id == tournament_id)
            )
        ).scalar_one()
    assert stored.source == TournamentResultSource.WALK_IN_EXISTING
    assert stored.place is None
    assert stored.knockouts_count == 0
    assert stored.big_knockouts_count == 0
    assert stored.tournament_points == Decimal("0.00")
    assert stored.knockout_points == Decimal("0.00")
    assert stored.bonus_points == 0
    await engine.dispose()


async def test_add_new_player_to_past_tournament_rejects_duplicate_name(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'past_add_new.db'}")
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
        existing = build_player(telegram_id=101, display_name="Same Name")
        session.add_all([season, admin, existing])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.commit()
        tournament_id = tournament.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    with pytest.raises(ResultDuplicateNameError):
        await service.add_new_player_to_tournament(100, tournament_id, " same   name ")

    async with session_factory() as session:
        result_count = len((await session.execute(select(TournamentResult))).scalars().all())
    assert result_count == 0
    await engine.dispose()


async def test_tournament_photos_limit_duplicates_and_delete_all(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'photos.db'}")
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
        session.add_all([season, admin])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.commit()
        tournament_id = tournament.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    first = await service.add_tournament_photo(
        100,
        tournament_id,
        telegram_file_id="file-1",
        telegram_file_unique_id="unique-1",
    )
    duplicate = await service.add_tournament_photo(
        100,
        tournament_id,
        telegram_file_id="file-1-again",
        telegram_file_unique_id="unique-1",
    )
    for index in range(2, 11):
        await service.add_tournament_photo(
            100,
            tournament_id,
            telegram_file_id=f"file-{index}",
            telegram_file_unique_id=f"unique-{index}",
        )
    over_limit = await service.add_tournament_photo(
        100,
        tournament_id,
        telegram_file_id="file-11",
        telegram_file_unique_id="unique-11",
    )

    assert first.created is True
    assert duplicate.created is False
    assert over_limit.limit_reached is True
    assert len(await service.list_tournament_photos(100, tournament_id)) == 10

    results = await service.delete_tournament_photos(100, tournament_id)

    assert results.photo_count == 0
    assert await service.list_tournament_photos(100, tournament_id) == []
    await engine.dispose()


async def test_close_tournament_rejects_future_tournament_without_mutation(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'future_close.db'}")
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
        player = build_player(
            telegram_id=101,
            display_name="Player",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, superadmin, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 21),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add(
            TournamentResult(
                tournament_id=tournament.id,
                player_id=player.id,
                source=TournamentResultSource.REGISTERED,
                checked_in_by_user_id=superadmin.id,
                place=1,
            )
        )
        await session.commit()
        tournament_id = tournament.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    with pytest.raises(FutureTournamentCannotBeClosedError):
        await service.close_tournament(100, tournament_id, 1000)

    async with session_factory() as session:
        tournament = await session.get(Tournament, tournament_id)
        result = (
            await session.execute(
                select(TournamentResult).where(TournamentResult.tournament_id == tournament_id)
            )
        ).scalar_one()

    assert tournament is not None
    assert tournament.status == TournamentStatus.ACTIVE
    assert tournament.tournament_fund is None
    assert result.tournament_points == Decimal("0.00")
    assert result.knockout_points == Decimal("0.00")
    await engine.dispose()


async def test_result_rejects_duplicate_place_for_live_edit(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'duplicates.db'}")
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
        players = [
            build_player(telegram_id=101, display_name="First", status=UserStatus.ACTIVE),
            build_player(telegram_id=102, display_name="Second", status=UserStatus.ACTIVE),
        ]
        session.add_all([season, admin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            TournamentResult(
                tournament_id=tournament.id,
                player_id=player.id,
                source=TournamentResultSource.REGISTERED,
                checked_in_by_user_id=admin.id,
            )
            for player in players
        )
        await session.commit()
        tournament_id = tournament.id
        player_ids = [player.id for player in players]

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 18, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    await service.update_player_result_field(
        100, tournament_id, player_ids[0], ResultField.PLACE, 1
    )
    with pytest.raises(ResultInvalidPlayerDataError):
        await service.update_player_result_field(
            100, tournament_id, player_ids[1], ResultField.PLACE, 1
        )

    results = await service.get_tournament_results(100, tournament_id)

    assert [(player.player_id, player.place) for player in results.players] == [
        (player_ids[0], 1),
        (player_ids[1], None),
    ]

    try:
        await service.update_player_result_field(
            100, tournament_id, player_ids[0], ResultField.PLACE, 7
        )
    except ResultInvalidPlayerDataError:
        pass
    else:
        raise AssertionError("Expected ResultInvalidPlayerDataError")
    await engine.dispose()


async def test_results_use_checked_in_rows_not_pre_registrations(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'check_in_rows.db'}")
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
        registered_no_show = build_player(
            telegram_id=101,
            display_name="No Show",
            status=UserStatus.ACTIVE,
        )
        registered_checked_in = build_player(
            telegram_id=102,
            display_name="Checked In",
            status=UserStatus.ACTIVE,
        )
        walk_in = build_player(
            telegram_id=103,
            display_name="Walk In",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, admin, registered_no_show, registered_checked_in, walk_in])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=registered_no_show.id,
                ),
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=registered_checked_in.id,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=registered_checked_in.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=admin.id,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=walk_in.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=admin.id,
                ),
            ]
        )
        await session.commit()
        tournament_id = tournament.id
        expected_player_ids = [registered_checked_in.id, walk_in.id]

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 18, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    results = await service.get_tournament_results(100, tournament_id)

    assert [player.player_id for player in results.players] == expected_player_ids
    await engine.dispose()


async def test_stale_yesterday_result_callback_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stale_results.db'}")
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
            date=date(2026, 7, 19),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        result = TournamentResult(
            tournament_id=tournament.id,
            player_id=player.id,
            source=TournamentResultSource.REGISTERED,
            checked_in_by_user_id=admin.id,
        )
        session.add(result)
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    await service.update_player_result_field(
        100,
        tournament_id,
        player_id,
        ResultField.PLACE,
        1,
    )

    async with session_factory() as session:
        stored = (
            await session.execute(
                select(TournamentResult).where(TournamentResult.tournament_id == tournament_id)
            )
        ).scalar_one()
    assert stored.place == 1
    await engine.dispose()
