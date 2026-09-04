from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import (
    build_player,
    seed_tournament_rules_async,
    seed_tournament_types_async,
    tournament_type_id,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    PlayerReward,
    ScoringConfig,
    Season,
    Tournament,
    TournamentCombination,
    TournamentPhoto,
    TournamentRegistration,
    TournamentResult,
    TournamentTypeRule,
    User,
)
from app.db.models.enums import (
    KnockoutMode,
    PlayerRewardType,
    TournamentCombinationType,
    TournamentResultSource,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.services.access_policy import ActiveUserRequiredError, AdminAccessDeniedError
from app.services.result_fields import ResultField
from app.services.result_service import (
    ClosedTournamentCorrectionStaleError,
    FutureTournamentCannotBeClosedError,
    ResultCombinationAlreadyExistsError,
    ResultDuplicateNameError,
    ResultInvalidFundError,
    ResultInvalidPlayerDataError,
    ResultPlayerAlreadyAddedError,
    ResultPlayerRewardConflictError,
    ResultService,
    ResultTodayTournamentNotFoundError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    TournamentResultsEditingUnavailableError,
)
from app.services.tournament_combination_service import TournamentCombinationService
from app.services.tournament_participant_service import TournamentParticipantService
from app.services.tournament_photo_service import TournamentPhotoService


@pytest.mark.parametrize("fund", [None, 0, -10, 105, Decimal("10.5")])
def test_live_close_fund_validation_rejects_invalid_values(fund: object) -> None:
    with pytest.raises(ResultInvalidFundError):
        ResultService.validate_tournament_fund(fund)  # type: ignore[arg-type]


def test_live_close_fund_validation_accepts_valid_value() -> None:
    assert ResultService.validate_tournament_fund(1000) == 1000


async def _build_open_delete_service(
    database_path: Path,
    *,
    tournament_status: TournamentStatus = TournamentStatus.ACTIVE,
    tournament_date: date = date(2026, 8, 26),
) -> tuple[TournamentParticipantService, async_sessionmaker, object, dict[str, int]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
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
            starts_at=date(2026, 8, 1),
            ends_at=None,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        admin = build_player(
            telegram_id=101,
            display_name="Admin",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        player_actor = build_player(
            telegram_id=102,
            display_name="Player Actor",
            status=UserStatus.ACTIVE,
            role=UserRole.PLAYER,
        )
        first = build_player(telegram_id=201, display_name="Первый", status=UserStatus.ACTIVE)
        second = build_player(telegram_id=202, display_name="Второй", status=UserStatus.ACTIVE)
        other_only = build_player(
            telegram_id=203,
            display_name="Только другой",
            status=UserStatus.ACTIVE,
        )
        session.add_all([season, superadmin, admin, player_actor, first, second, other_only])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("mystery_bounty"),
            date=tournament_date,
            status=tournament_status,
            tournament_fund=10 if tournament_status == TournamentStatus.CLOSED else None,
        )
        other_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 8, 25),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([tournament, other_tournament])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=first.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=1,
                    knockouts_count=2,
                    big_knockouts_count=1,
                    bonus_points=5,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=second.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                ),
                TournamentResult(
                    tournament_id=other_tournament.id,
                    player_id=first.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=2,
                ),
                TournamentResult(
                    tournament_id=other_tournament.id,
                    player_id=other_only.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=3,
                ),
                TournamentRegistration(tournament_id=tournament.id, player_id=first.id),
                TournamentRegistration(tournament_id=other_tournament.id, player_id=first.id),
                TournamentCombination(
                    tournament_id=tournament.id,
                    player_id=first.id,
                    combination_type=TournamentCombinationType.STRAIGHT_FLUSH,
                ),
                TournamentCombination(
                    tournament_id=other_tournament.id,
                    player_id=first.id,
                    combination_type=TournamentCombinationType.ROYAL_FLUSH,
                ),
            ]
        )
        ids = {
            "tournament": tournament.id,
            "other_tournament": other_tournament.id,
            "first": first.id,
            "second": second.id,
            "other_only": other_only.id,
        }
        await session.commit()
    service = TournamentParticipantService(
        session_factory,
        clock=FixedClock(datetime(2026, 8, 26, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    return service, session_factory, engine, ids


async def test_delete_player_from_open_tournament_removes_scoped_rows_only(
    tmp_path: Path,
) -> None:
    service, session_factory, engine, ids = await _build_open_delete_service(
        tmp_path / "open-delete.db"
    )
    try:
        result = await service.delete_player_from_open_tournament(
            superadmin_telegram_id=100,
            tournament_id=ids["tournament"],
            player_id=ids["first"],
        )

        assert result.player.display_name == "Первый"
        assert result.deleted_registration is True
        assert result.deleted_combinations_count == 1
        async with session_factory() as session:
            results = (await session.execute(select(TournamentResult))).scalars().all()
            registrations = (await session.execute(select(TournamentRegistration))).scalars().all()
            combinations = (await session.execute(select(TournamentCombination))).scalars().all()
            users = [user.display_name for user in (await session.execute(select(User))).scalars()]

        assert (ids["tournament"], ids["first"]) not in {
            (item.tournament_id, item.player_id) for item in results
        }
        assert (ids["other_tournament"], ids["first"]) in {
            (item.tournament_id, item.player_id) for item in results
        }
        assert (ids["tournament"], ids["first"]) not in {
            (item.tournament_id, item.player_id) for item in registrations
        }
        assert (ids["other_tournament"], ids["first"]) in {
            (item.tournament_id, item.player_id) for item in registrations
        }
        assert (ids["tournament"], ids["first"]) not in {
            (item.tournament_id, item.player_id) for item in combinations
        }
        assert (ids["other_tournament"], ids["first"]) in {
            (item.tournament_id, item.player_id) for item in combinations
        }
        assert "Первый" in users
    finally:
        await engine.dispose()


async def test_delete_player_from_open_tournament_refreshes_readiness(
    tmp_path: Path,
) -> None:
    service, _, engine, ids = await _build_open_delete_service(tmp_path / "readiness.db")
    result_service = ResultService(
        service.session_factory,
        clock=FixedClock(datetime(2026, 8, 26, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        before = await result_service.get_close_readiness(100, ids["tournament"])

        await service.delete_player_from_open_tournament(
            superadmin_telegram_id=100,
            tournament_id=ids["tournament"],
            player_id=ids["first"],
        )
        after = await result_service.get_close_readiness(100, ids["tournament"])

        assert before.players_count == 2
        assert after.players_count == 1
    finally:
        await engine.dispose()


async def test_open_tournament_delete_player_list_uses_selected_tournament_only(
    tmp_path: Path,
) -> None:
    service, _, engine, ids = await _build_open_delete_service(tmp_path / "delete-list.db")
    try:
        page = await service.list_open_tournament_players_for_delete(
            superadmin_telegram_id=100,
            tournament_id=ids["tournament"],
            page=0,
        )

        assert {player.player_id for player in page.items} == {ids["first"], ids["second"]}
        assert ids["other_only"] not in {player.player_id for player in page.items}
    finally:
        await engine.dispose()


async def test_delete_player_from_open_tournament_requires_superadmin(
    tmp_path: Path,
) -> None:
    service, _, engine, ids = await _build_open_delete_service(tmp_path / "delete-auth.db")
    try:
        with pytest.raises(AdminAccessDeniedError):
            await service.delete_player_from_open_tournament(
                superadmin_telegram_id=101,
                tournament_id=ids["tournament"],
                player_id=ids["first"],
            )
    finally:
        await engine.dispose()


async def test_delete_player_from_open_tournament_rejects_closed_and_stale_player(
    tmp_path: Path,
) -> None:
    service, _, engine, ids = await _build_open_delete_service(
        tmp_path / "delete-closed.db",
        tournament_status=TournamentStatus.CLOSED,
    )
    try:
        with pytest.raises(ResultTournamentNotFoundError):
            await service.delete_player_from_open_tournament(
                superadmin_telegram_id=100,
                tournament_id=ids["tournament"],
                player_id=ids["first"],
            )
        with pytest.raises(ResultTournamentNotFoundError):
            await service.get_open_tournament_player_delete_preview(
                superadmin_telegram_id=100,
                tournament_id=ids["tournament"],
                player_id=ids["first"],
            )
    finally:
        await engine.dispose()

    service, _, engine, ids = await _build_open_delete_service(
        tmp_path / "delete-future.db",
        tournament_date=date(2026, 8, 27),
    )
    try:
        with pytest.raises(FutureTournamentCannotBeClosedError):
            await service.delete_player_from_open_tournament(
                superadmin_telegram_id=100,
                tournament_id=ids["tournament"],
                player_id=ids["first"],
            )
    finally:
        await engine.dispose()

    service, _, engine, ids = await _build_open_delete_service(tmp_path / "delete-stale.db")
    try:
        with pytest.raises(ResultUserNotFoundError):
            await service.delete_player_from_open_tournament(
                superadmin_telegram_id=100,
                tournament_id=ids["tournament"],
                player_id=999,
            )
    finally:
        await engine.dispose()


async def test_delete_player_from_open_tournament_blocks_existing_reward(
    tmp_path: Path,
) -> None:
    service, session_factory, engine, ids = await _build_open_delete_service(
        tmp_path / "delete-reward.db"
    )
    try:
        async with session_factory() as session:
            session.add(
                PlayerReward(
                    player_id=ids["first"],
                    reward_type=PlayerRewardType.PRIZE_STACK_BONUS,
                    chips_amount=40_000,
                    source_tournament_id=ids["tournament"],
                    source_place=1,
                    issued_at=datetime(2026, 8, 26, 20, tzinfo=ZoneInfo("Europe/Moscow")),
                    valid_through=date(2026, 9, 2),
                )
            )
            await session.commit()

        with pytest.raises(ResultPlayerRewardConflictError):
            await service.delete_player_from_open_tournament(
                superadmin_telegram_id=100,
                tournament_id=ids["tournament"],
                player_id=ids["first"],
            )
    finally:
        await engine.dispose()


async def test_delete_player_from_open_tournament_rolls_back_on_delete_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine, ids = await _build_open_delete_service(
        tmp_path / "delete-rollback.db"
    )

    async def fail_delete(self: TournamentResultRepository, result: TournamentResult) -> None:
        raise RuntimeError("delete failed")

    monkeypatch.setattr(TournamentResultRepository, "delete", fail_delete)
    try:
        with pytest.raises(RuntimeError, match="delete failed"):
            await service.delete_player_from_open_tournament(
                superadmin_telegram_id=100,
                tournament_id=ids["tournament"],
                player_id=ids["first"],
            )

        async with session_factory() as session:
            assert (
                await session.execute(
                    select(TournamentResult).where(
                        TournamentResult.tournament_id == ids["tournament"],
                        TournamentResult.player_id == ids["first"],
                    )
                )
            ).scalar_one_or_none() is not None
            assert (
                await session.execute(
                    select(TournamentRegistration).where(
                        TournamentRegistration.tournament_id == ids["tournament"],
                        TournamentRegistration.player_id == ids["first"],
                    )
                )
            ).scalar_one_or_none() is not None
            assert (
                await session.execute(
                    select(TournamentCombination).where(
                        TournamentCombination.tournament_id == ids["tournament"],
                        TournamentCombination.player_id == ids["first"],
                    )
                )
            ).scalar_one_or_none() is not None
    finally:
        await engine.dispose()


async def test_tournament_combinations_can_be_added_deleted_and_deduplicated(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'combinations.db'}")
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
        first = build_player(telegram_id=None, display_name="Борис", status=UserStatus.ACTIVE)
        second = build_player(telegram_id=None, display_name="Алексей", status=UserStatus.ACTIVE)
        session.add_all([season, admin, first, second])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 19),
            status=TournamentStatus.ACTIVE,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=first.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=admin.id,
                ),
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=second.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=admin.id,
                ),
            ]
        )
        tournament_id = tournament.id
        first_id = first.id
        await session.commit()

    combination_service = TournamentCombinationService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 19, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    view = await combination_service.add_combination(
        admin_telegram_id=100,
        tournament_id=tournament_id,
        player_id=first_id,
        combination_type=TournamentCombinationType.STRAIGHT_FLUSH,
    )

    assert [(item.display_name, item.combination_type) for item in view.combinations] == [
        ("Борис", "straight_flush")
    ]
    assert [player.display_name for player in view.players] == ["Алексей", "Борис"]
    with pytest.raises(ResultCombinationAlreadyExistsError):
        await combination_service.add_combination(
            admin_telegram_id=100,
            tournament_id=tournament_id,
            player_id=first_id,
            combination_type=TournamentCombinationType.STRAIGHT_FLUSH,
        )
    combination_id = view.combinations[0].id
    empty = await combination_service.delete_combination(
        admin_telegram_id=100,
        tournament_id=tournament_id,
        combination_id=combination_id,
    )

    assert empty.combinations == []
    async with session_factory() as session:
        combinations = (await session.execute(select(TournamentCombination))).scalars().all()
    assert combinations == []
    await engine.dispose()


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


async def test_today_result_entry_uses_tournament_day_boundary(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'boundary_results.db'}")
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
            ]
        )
        await session.commit()

    before_start = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 5, tzinfo=ZoneInfo("Europe/Moscow"))),
        tournament_day_start_hour=11,
    )
    at_start = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 11, tzinfo=ZoneInfo("Europe/Moscow"))),
        tournament_day_start_hour=11,
    )

    assert (await before_start.get_today_tournament_results(100)).tournament.date == date(
        2026,
        7,
        19,
    )
    assert (await at_start.get_today_tournament_results(100)).tournament.date == date(
        2026,
        7,
        20,
    )
    await engine.dispose()


async def test_superadmin_close_horizon_uses_tournament_day_boundary(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'close_boundary.db'}")
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
        session.add_all([season, superadmin])
        await session.flush()
        previous_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 19),
            status=TournamentStatus.ACTIVE,
        )
        current_tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("freezeout"),
            date=date(2026, 7, 20),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([previous_tournament, current_tournament])
        await session.commit()
        previous_tournament_id = previous_tournament.id
        current_tournament_id = current_tournament.id

    before_start = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 5, tzinfo=ZoneInfo("Europe/Moscow"))),
        tournament_day_start_hour=11,
    )
    at_start = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 11, tzinfo=ZoneInfo("Europe/Moscow"))),
        tournament_day_start_hour=11,
    )

    before_start_items = await before_start.list_unclosed_tournaments_for_superadmin(100)
    at_start_items = await at_start.list_unclosed_tournaments_for_superadmin(100)

    assert [item.tournament.id for item in before_start_items] == [previous_tournament_id]
    assert {item.tournament.id for item in at_start_items} == {
        previous_tournament_id,
        current_tournament_id,
    }
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


async def test_deep_stack_uses_ordinary_multiplier_without_changing_double_double(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'format-multipliers.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        await seed_tournament_rules_async(session)
        season = Season(
            name="Test season",
            scoring_config_id=config.id,
            starts_at=date(2026, 9, 1),
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
                telegram_id=telegram_id,
                display_name=f"Player {telegram_id}",
                status=UserStatus.ACTIVE,
            )
            for telegram_id in range(201, 211)
        ]
        session.add_all([season, superadmin, *players])
        await session.flush()
        double_double = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("double_double"),
            date=date(2026, 9, 5),
            status=TournamentStatus.ACTIVE,
        )
        deep_stack = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("deep_stack"),
            date=date(2026, 9, 6),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([double_double, deep_stack])
        await session.flush()
        for tournament, tournament_players in (
            (double_double, players[:5]),
            (deep_stack, players[5:]),
        ):
            session.add(
                TournamentPhoto(
                    tournament_id=tournament.id,
                    telegram_file_id=f"file-{tournament.id}",
                    telegram_file_unique_id=f"unique-{tournament.id}",
                    uploaded_by_user_id=superadmin.id,
                    position=0,
                )
            )
            session.add_all(
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    place=index,
                    checked_in_by_user_id=superadmin.id,
                )
                for index, player in enumerate(tournament_players, start=1)
            )
        await session.commit()

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 9, 7, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )

    double_double_preview = await service.preview_tournament_close(
        100,
        double_double.id,
        1000,
    )
    deep_stack_preview = await service.preview_tournament_close(
        100,
        deep_stack.id,
        1000,
    )

    assert double_double_preview.players[0].tournament_points == Decimal("900.00")
    assert deep_stack_preview.players[0].tournament_points == Decimal("450.00")
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


async def test_mystery_bounty_uses_places_knockouts_and_bonus_without_big_knockouts(
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
                knockout_mode=KnockoutMode.SMALL,
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

    assert results.knockout_mode == KnockoutMode.SMALL.value
    assert results.supports_bonus_points is True
    assert ResultService.editable_result_fields(results) == [
        ResultField.PLACE,
        ResultField.KNOCKOUTS,
        ResultField.BONUS,
    ]
    assert ResultField.BIG_KNOCKOUTS not in ResultService.editable_result_fields(results)
    assert await service.validate_results(100, tournament_id) == [
        "Введи места: 1, 2, 3, 4, 5.",
        "Введи хотя бы один 🥊.",
    ]

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
        ResultField.KNOCKOUTS,
        3,
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
    assert player.knockout_points == Decimal("45.00")
    assert player.total_points == Decimal("457.00")
    await engine.dispose()


async def test_closed_mystery_bounty_correction_updates_knockouts_without_big_knockouts(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'closed_mystery.db'}")
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
                knockout_mode=KnockoutMode.SMALL,
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
        session.add(
            TournamentPhoto(
                tournament_id=tournament.id,
                telegram_file_id="mystery-file-1",
                telegram_file_unique_id="mystery-unique-1",
                uploaded_by_user_id=superadmin.id,
                position=0,
            )
        )
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=superadmin.id,
                    place=place,
                    knockouts_count=3 if place == 1 else 0,
                )
                for place, player in enumerate(players, start=1)
            ]
        )
        await session.commit()
        tournament_id = tournament.id
        first_player_id = players[0].id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 18, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    await service.close_tournament(100, tournament_id, 1000)
    results = await service.get_closed_tournament_results(100, tournament_id)

    assert results.knockout_mode == KnockoutMode.SMALL.value
    assert ResultService.editable_result_fields(results) == [
        ResultField.PLACE,
        ResultField.KNOCKOUTS,
        ResultField.BONUS,
    ]
    assert ResultField.BIG_KNOCKOUTS not in ResultService.editable_result_fields(results)

    draft = await service.begin_closed_tournament_correction(100, tournament_id)
    draft = await service.update_closed_tournament_draft_result_field(
        100,
        draft,
        first_player_id,
        ResultField.KNOCKOUTS,
        5,
    )
    updated = await service.get_closed_tournament_draft_results(100, draft)
    player = ResultService.find_result_player(updated, first_player_id)
    assert player is not None
    assert player.knockout_points == Decimal("75.00")
    persisted = ResultService.find_result_player(
        await service.get_closed_tournament_results(100, tournament_id),
        first_player_id,
    )
    assert persisted is not None
    assert persisted.knockouts_count == 3

    correction = await service.build_closed_tournament_correction_preview(100, draft)

    assert [
        (change.display_name, [(field.label, field.before, field.after) for field in change.fields])
        for change in correction.result_changes
    ] == [("Player 1", [("КО", "3", "5")])]
    assert correction.reward_changes == ()
    await service.apply_closed_tournament_correction(100, draft)
    await engine.dispose()


async def test_closed_correction_stale_draft_is_rejected(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'closed_stale.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed_tournament_types_async(session)
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        season = Season(
            name="Season",
            starts_at=date(2026, 7, 1),
            ends_at=None,
            scoring_config_id=config.id,
        )
        superadmin = build_player(
            telegram_id=100,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        players = [
            build_player(
                telegram_id=None,
                display_name=f"Player {index}",
                status=UserStatus.ACTIVE,
            )
            for index in range(1, 6)
        ]
        session.add_all([season, superadmin, *players])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 18),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        session.add(tournament)
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=superadmin.id,
                    place=index,
                )
                for index, player in enumerate(players, start=1)
            ]
        )
        await session.commit()
        tournament_id = tournament.id
        first_player_id = players[0].id

    service = ResultService(session_factory)
    draft = await service.begin_closed_tournament_correction(100, tournament_id)
    draft = await service.update_closed_tournament_draft_result_field(
        100,
        draft,
        first_player_id,
        ResultField.PLACE,
        2,
    )
    async with session_factory() as session:
        result = await TournamentResultRepository(session).get_by_tournament_and_player(
            tournament_id,
            first_player_id,
        )
        assert result is not None
        result.knockouts_count = 1
        await session.commit()

    with pytest.raises(ClosedTournamentCorrectionStaleError):
        await service.apply_closed_tournament_correction(100, draft)
    await engine.dispose()


async def test_closed_correction_add_delete_and_fund_are_draft_only(tmp_path: Path) -> None:
    participant_service, session_factory, engine, ids = await _build_open_delete_service(
        tmp_path / "closed-draft-only.db",
        tournament_status=TournamentStatus.CLOSED,
    )
    service = ResultService(
        participant_service.session_factory,
        clock=FixedClock(datetime(2026, 8, 26, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        draft = await service.begin_closed_tournament_correction(100, ids["tournament"])

        candidates = await service.search_closed_draft_add_player_users(
            100,
            draft,
            query="Только",
        )
        assert [candidate.id for candidate in candidates] == [ids["other_only"]]

        draft = await service.add_closed_tournament_draft_existing_player(
            100,
            draft,
            user_id=ids["other_only"],
        )
        draft = await service.delete_closed_tournament_draft_player(
            100,
            draft,
            player_id=ids["second"],
        )
        draft = await service.update_closed_tournament_draft_fund(100, draft, 2000)
        draft_results = await service.get_closed_tournament_draft_results(100, draft)

        assert {player.player_id for player in draft_results.players} == {
            ids["first"],
            ids["other_only"],
        }
        assert draft_results.tournament_fund == 2000

        async with session_factory() as session:
            persisted_results = (
                await session.execute(
                    select(TournamentResult).where(
                        TournamentResult.tournament_id == ids["tournament"]
                    )
                )
            ).scalars()
            persisted_player_ids = {result.player_id for result in persisted_results}
            tournament = await session.get(Tournament, ids["tournament"])
            assert tournament is not None

        assert persisted_player_ids == {ids["first"], ids["second"]}
        assert tournament.tournament_fund == 10
    finally:
        await engine.dispose()


async def test_closed_correction_duplicate_draft_player_is_rejected(tmp_path: Path) -> None:
    participant_service, _session_factory, engine, ids = await _build_open_delete_service(
        tmp_path / "closed-duplicate-player.db",
        tournament_status=TournamentStatus.CLOSED,
    )
    service = ResultService(
        participant_service.session_factory,
        clock=FixedClock(datetime(2026, 8, 26, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        draft = await service.begin_closed_tournament_correction(100, ids["tournament"])

        with pytest.raises(ResultPlayerAlreadyAddedError):
            await service.add_closed_tournament_draft_existing_player(
                100,
                draft,
                user_id=ids["first"],
            )
    finally:
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

    service = TournamentParticipantService(
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


async def test_add_existing_player_to_tournament_rejects_duplicate_and_missing_user(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'participant_add_errors.db'}")
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
        await session.flush()
        session.add(
            TournamentResult(
                tournament_id=tournament.id,
                player_id=player.id,
                source=TournamentResultSource.WALK_IN_EXISTING,
                checked_in_by_user_id=admin.id,
            )
        )
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = TournamentParticipantService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    try:
        with pytest.raises(ResultPlayerAlreadyAddedError):
            await service.add_existing_player_to_tournament(100, tournament_id, player_id)
        with pytest.raises(ResultUserNotFoundError):
            await service.add_existing_player_to_tournament(100, tournament_id, 999)
    finally:
        await engine.dispose()


async def test_add_existing_player_to_tournament_enforces_auth_and_editable_scope(
    tmp_path: Path,
) -> None:
    service, _, engine, ids = await _build_open_delete_service(
        tmp_path / "participant_add_auth.db",
        tournament_date=date(2026, 8, 27),
    )
    try:
        with pytest.raises(ActiveUserRequiredError):
            await service.add_existing_player_to_tournament(
                admin_telegram_id=999,
                tournament_id=ids["tournament"],
                user_id=ids["other_only"],
            )
        with pytest.raises(AdminAccessDeniedError):
            await service.add_existing_player_to_tournament(
                admin_telegram_id=102,
                tournament_id=ids["tournament"],
                user_id=ids["other_only"],
            )
        with pytest.raises(TournamentResultsEditingUnavailableError):
            await service.add_existing_player_to_tournament(
                admin_telegram_id=101,
                tournament_id=ids["tournament"],
                user_id=ids["other_only"],
            )
    finally:
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

    service = TournamentParticipantService(
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

    result_service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    photo_service = TournamentPhotoService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    first = await photo_service.add_photo(
        100,
        tournament_id,
        telegram_file_id="file-1",
        telegram_file_unique_id="unique-1",
    )
    duplicate = await photo_service.add_photo(
        100,
        tournament_id,
        telegram_file_id="file-1-again",
        telegram_file_unique_id="unique-1",
    )
    for index in range(2, 11):
        await photo_service.add_photo(
            100,
            tournament_id,
            telegram_file_id=f"file-{index}",
            telegram_file_unique_id=f"unique-{index}",
        )
    over_limit = await photo_service.add_photo(
        100,
        tournament_id,
        telegram_file_id="file-11",
        telegram_file_unique_id="unique-11",
    )

    assert first.created is True
    assert duplicate.created is False
    assert over_limit.limit_reached is True
    assert len(await photo_service.list_for_tournament(100, tournament_id)) == 10

    deleted = await photo_service.delete_photos(100, tournament_id)
    results = await result_service.get_tournament_results(100, tournament_id)

    assert deleted == 10
    assert results.photo_count == 0
    assert await photo_service.list_for_tournament(100, tournament_id) == []
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


async def test_result_reassigns_occupied_place_for_live_edit(
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
    await service.update_player_result_field(
        100, tournament_id, player_ids[1], ResultField.PLACE, 1
    )

    results = await service.get_tournament_results(100, tournament_id)

    assert [(player.player_id, player.place) for player in results.players] == [
        (player_ids[0], None),
        (player_ids[1], 1),
    ]
    await service.update_player_result_field(
        100, tournament_id, player_ids[1], ResultField.PLACE, 1
    )
    results = await service.get_tournament_results(100, tournament_id)
    assert [(player.player_id, player.place) for player in results.players] == [
        (player_ids[0], None),
        (player_ids[1], 1),
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


async def test_admin_previous_open_result_callback_uses_existing_result_policy(
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


async def test_superadmin_can_edit_previous_open_tournament_results_photos_and_combinations(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'superadmin_open_edit.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        session.add(
            TournamentTypeRule(
                tournament_type_id=tournament_type_id("classic"),
                knockout_mode=KnockoutMode.SMALL_BIG,
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
        player = build_player(telegram_id=101, display_name="Player", status=UserStatus.ACTIVE)
        session.add_all([season, superadmin, player])
        await session.flush()
        tournament = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 19),
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
            )
        )
        await session.commit()
        tournament_id = tournament.id
        player_id = player.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    photo_service = TournamentPhotoService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )
    combination_service = TournamentCombinationService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )

    results = await service.update_player_result_field(
        100,
        tournament_id,
        player_id,
        ResultField.PLACE,
        1,
    )
    photo = await photo_service.add_photo(
        100,
        tournament_id,
        telegram_file_id="file-1",
        telegram_file_unique_id="unique-1",
    )
    combinations = await combination_service.add_combination(
        100,
        tournament_id,
        player_id,
        TournamentCombinationType.STRAIGHT_FLUSH,
    )

    assert ResultService.find_result_player(results, player_id).place == 1
    assert photo.created is True
    assert [combination.player_id for combination in combinations.combinations] == [player_id]
    await engine.dispose()


async def test_result_tournament_navigation_preserves_admin_scope_and_expands_superadmin(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'editable_tournaments.db'}")
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
        superadmin = build_player(
            telegram_id=101,
            display_name="Superadmin",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        session.add_all([season, admin, superadmin])
        await session.flush()
        previous = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 19),
            status=TournamentStatus.ACTIVE,
        )
        current = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("freezeout"),
            date=date(2026, 7, 20),
            status=TournamentStatus.ACTIVE,
        )
        future = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 21),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([previous, current, future])
        await session.commit()
        previous_id = previous.id
        current_id = current.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )

    admin_tournaments = await service.list_editable_tournaments(100)
    superadmin_tournaments = await service.list_editable_tournaments(101)

    assert [tournament.id for tournament in admin_tournaments] == [current_id]
    assert [tournament.id for tournament in superadmin_tournaments] == [
        current_id,
        previous_id,
    ]
    await engine.dispose()


async def test_superadmin_open_edit_rejects_future_and_closed_tournaments(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'superadmin_open_edit_gate.db'}")
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
        closed = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 19),
            status=TournamentStatus.CLOSED,
            tournament_fund=1000,
        )
        future = Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("classic"),
            date=date(2026, 7, 21),
            status=TournamentStatus.ACTIVE,
        )
        session.add_all([closed, future])
        await session.flush()
        session.add_all(
            [
                TournamentResult(
                    tournament_id=closed.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=superadmin.id,
                ),
                TournamentResult(
                    tournament_id=future.id,
                    player_id=player.id,
                    source=TournamentResultSource.REGISTERED,
                    checked_in_by_user_id=superadmin.id,
                ),
            ]
        )
        await session.commit()
        closed_id = closed.id
        future_id = future.id
        player_id = player.id

    service = ResultService(
        session_factory,
        clock=FixedClock(datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Europe/Moscow"))),
    )

    with pytest.raises(ResultTournamentNotFoundError):
        await service.update_player_result_field(
            100,
            closed_id,
            player_id,
            ResultField.PLACE,
            1,
        )
    with pytest.raises(TournamentResultsEditingUnavailableError):
        await service.update_player_result_field(
            100,
            future_id,
            player_id,
            ResultField.PLACE,
            1,
        )
    await engine.dispose()
