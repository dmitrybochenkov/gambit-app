from datetime import date, datetime
from pathlib import Path

import pytest
from conftest import (
    build_player,
    seed_tournament_configs_async,
    seed_tournament_types_async,
    seed_weekly_templates_async,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import ScoringConfig, Season, Tournament
from app.db.models.enums import TournamentStatus, UserRole, UserStatus
from app.services.access_policy import AdminAccessDeniedError
from app.services.tournament_planning_service import (
    CalendarPlanStaleError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarWeeklyPlanIntegrityError,
    TournamentPlanningService,
    WeeklyPlanningStatus,
    WeeklyTournamentPlan,
    next_complete_game_week,
)
from app.services.tournament_schedule_service import TournamentScheduleService


async def create_planning_service(
    database_path: Path,
    *,
    today: date = date(2026, 8, 9),
) -> tuple[TournamentPlanningService, async_sessionmaker, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return (
        TournamentPlanningService(
            session_factory,
            clock=FixedClock(datetime.combine(today, datetime.min.time())),
        ),
        session_factory,
        engine,
    )


async def seed_calendar_data(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        await seed_tournament_configs_async(session)
        await seed_weekly_templates_async(session)
        session.add_all(
            [
                build_player(
                    telegram_id=100,
                    display_name="Superadmin",
                    status=UserStatus.ACTIVE,
                    role=UserRole.SUPERADMIN,
                ),
                Season(
                    name="Лето 2026",
                    scoring_config_id=config.id,
                    starts_at=date(2026, 6, 1),
                    ends_at=None,
                ),
            ]
        )
        await session.commit()


async def seed_week_tournaments(
    session_factory: async_sessionmaker,
    *,
    dates: list[date],
    status: TournamentStatus,
    tournament_type_id: int = 1,
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                Tournament(
                    season_id=1,
                    tournament_type_id=tournament_type_id,
                    date=tournament_date,
                    tournament_fund=10 if status == TournamentStatus.CLOSED else None,
                    status=status,
                )
                for tournament_date in dates
            ]
        )
        await session.commit()


async def test_next_complete_game_week_uses_wednesday_to_sunday() -> None:
    assert next_complete_game_week(date(2026, 8, 9)) == (
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
        date(2026, 8, 15),
        date(2026, 8, 16),
    )


async def test_weekly_plan_uses_last_existing_tournament_regression(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            for tournament_date in [
                date(2026, 8, 1),
                date(2026, 8, 6),
                date(2026, 8, 7),
                date(2026, 8, 8),
                date(2026, 8, 9),
            ]:
                session.add(
                    Tournament(
                        season_id=1,
                        tournament_type_id=1,
                        date=tournament_date,
                        tournament_fund=10,
                        status=TournamentStatus.CLOSED,
                    )
                )
            await session.commit()

        plan = await service.build_next_week_plan(100)

        assert [item.date for item in plan.tournaments] == [
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 15),
            date(2026, 8, 16),
        ]
        assert [item.tournament_type.name for item in plan.tournaments] == [
            "Баунти турнир",
            "Классика",
            "Фризаут",
            "Double Double",
            "Boss Bounty",
        ]
    finally:
        await engine.dispose()


async def test_weekly_plan_uses_real_sunday_rotation_history(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "rotation.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=5,
                    date=date(2026, 8, 9),
                    tournament_fund=10,
                    status=TournamentStatus.CLOSED,
                )
            )
            await session.commit()

        plan = await service.build_next_week_plan(100)

        assert plan.tournaments[-1].date == date(2026, 8, 16)
        assert plan.tournaments[-1].tournament_type.name == "Boss Bounty"
    finally:
        await engine.dispose()


async def test_weekly_plan_ignores_cancelled_sunday_rotation_history(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "cancelled.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=5,
                    date=date(2026, 8, 9),
                    status=TournamentStatus.CANCELLED,
                )
            )
            await session.commit()

        plan = await service.build_next_week_plan(100)

        assert plan.tournaments[-1].tournament_type.name == "Boss Bounty"
    finally:
        await engine.dispose()


async def test_weekly_plan_can_be_edited_in_memory(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "edit.db")
    try:
        await seed_calendar_data(session_factory)
        plan_view = await service.build_next_week_plan(100)
        plan = WeeklyTournamentPlan.from_fsm(
            [
                {
                    "date": item.date.isoformat(),
                    "tournament_type_id": item.tournament_type.id,
                }
                for item in plan_view.tournaments
            ]
        )

        updated = await service.update_plan_day_type(
            100,
            plan,
            date(2026, 8, 13),
            3,
        )

        assert [item.tournament_type.name for item in updated.tournaments] == [
            "Баунти турнир",
            "Фризаут",
            "Фризаут",
            "Double Double",
            "Boss Bounty",
        ]
    finally:
        await engine.dispose()


async def test_manual_planning_check_reports_empty_partial_and_complete(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "states.db")
    try:
        await seed_calendar_data(session_factory)

        empty = await service.inspect_next_week(100)
        assert empty.status == WeeklyPlanningStatus.NEXT_WEEK_EMPTY
        assert empty.plan is not None
        assert len(empty.plan.tournaments) == 5

        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 12)],
            status=TournamentStatus.ACTIVE,
        )

        in_progress = await service.inspect_next_week(100)
        assert in_progress.status == WeeklyPlanningStatus.LATEST_WEEK_IN_PROGRESS
        assert in_progress.schedule is not None
        assert in_progress.schedule.tournaments[0].tournament_type_name == "Баунти турнир"
        assert in_progress.schedule.tournaments[1].tournament_type_name is None
    finally:
        await engine.dispose()


async def test_manual_planning_uses_db_progression_not_today(
    tmp_path: Path,
) -> None:
    for today in [date(2026, 8, 10), date(2026, 8, 12), date(2026, 8, 16)]:
        service, session_factory, engine = await create_planning_service(
            tmp_path / f"blocked-{today.isoformat()}.db",
            today=today,
        )
        try:
            await seed_calendar_data(session_factory)
            await seed_week_tournaments(
                session_factory,
                dates=[
                    date(2026, 8, 12),
                    date(2026, 8, 13),
                    date(2026, 8, 14),
                    date(2026, 8, 15),
                    date(2026, 8, 16),
                ],
                status=TournamentStatus.ACTIVE,
            )

            planning = await service.inspect_next_week(100)

            assert planning.status == WeeklyPlanningStatus.LATEST_WEEK_IN_PROGRESS
            assert planning.plan is None
            assert planning.schedule is not None
            assert [item.date for item in planning.schedule.tournaments] == [
                date(2026, 8, 12),
                date(2026, 8, 13),
                date(2026, 8, 14),
                date(2026, 8, 15),
                date(2026, 8, 16),
            ]
        finally:
            await engine.dispose()


async def test_finished_latest_week_with_missing_sunday_allows_next_week(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "missing-sun.db")
    try:
        await seed_calendar_data(session_factory)
        await seed_week_tournaments(
            session_factory,
            dates=[
                date(2026, 8, 12),
                date(2026, 8, 13),
                date(2026, 8, 14),
                date(2026, 8, 15),
            ],
            status=TournamentStatus.CLOSED,
        )

        planning = await service.inspect_next_week(100)

        assert planning.status == WeeklyPlanningStatus.NEXT_WEEK_EMPTY
        assert planning.plan is not None
        assert [item.date for item in planning.plan.tournaments] == [
            date(2026, 8, 19),
            date(2026, 8, 20),
            date(2026, 8, 21),
            date(2026, 8, 22),
            date(2026, 8, 23),
        ]
    finally:
        await engine.dispose()


async def test_close_trigger_inspects_next_week_after_week_is_finished(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "after-close.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    Tournament(
                        season_id=1,
                        tournament_type_id=1,
                        date=date(2026, 8, 12),
                        tournament_fund=10,
                        status=TournamentStatus.CLOSED,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=2,
                        date=date(2026, 8, 13),
                        tournament_fund=10,
                        status=TournamentStatus.CLOSED,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=3,
                        date=date(2026, 8, 14),
                        tournament_fund=10,
                        status=TournamentStatus.CLOSED,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=4,
                        date=date(2026, 8, 15),
                        tournament_fund=10,
                        status=TournamentStatus.CLOSED,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=5,
                        date=date(2026, 8, 16),
                        tournament_fund=10,
                        status=TournamentStatus.CLOSED,
                    ),
                ]
            )
            await session.commit()

        planning = await service.inspect_after_tournament_close(100, date(2026, 8, 16))

        assert planning.status == WeeklyPlanningStatus.NEXT_WEEK_EMPTY
        assert planning.plan is not None
        assert [item.date for item in planning.plan.tournaments] == [
            date(2026, 8, 19),
            date(2026, 8, 20),
            date(2026, 8, 21),
            date(2026, 8, 22),
            date(2026, 8, 23),
        ]
    finally:
        await engine.dispose()


async def test_closing_old_week_does_not_trigger_when_newer_week_is_active(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "old-close.db")
    try:
        await seed_calendar_data(session_factory)
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 5)],
            status=TournamentStatus.CLOSED,
        )
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 12)],
            status=TournamentStatus.ACTIVE,
        )

        planning = await service.inspect_after_tournament_close(100, date(2026, 8, 5))

        assert planning.status == WeeklyPlanningStatus.LATEST_WEEK_IN_PROGRESS
        assert planning.plan is None
    finally:
        await engine.dispose()


async def test_create_weekly_schedule_persists_five_tournaments_atomically(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "create.db")
    try:
        await seed_calendar_data(session_factory)
        plan_view = await service.build_next_week_plan(100)
        plan = WeeklyTournamentPlan.from_fsm(
            [
                {
                    "date": item.date.isoformat(),
                    "tournament_type_id": item.tournament_type.id,
                }
                for item in plan_view.tournaments
            ]
        )

        created = await service.create_weekly_schedule(100, plan)

        assert len(created.tournaments) == 5
        async with session_factory() as session:
            tournaments = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )
        assert [item.date for item in tournaments] == [
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 15),
            date(2026, 8, 16),
        ]
        assert {item.status for item in tournaments} == {TournamentStatus.ACTIVE}
    finally:
        await engine.dispose()


async def test_create_weekly_schedule_blocks_duplicate_date_and_rolls_back(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "conflict.db")
    try:
        await seed_calendar_data(session_factory)
        plan_view = await service.build_next_week_plan(100)
        plan = WeeklyTournamentPlan.from_fsm(
            [
                {
                    "date": item.date.isoformat(),
                    "tournament_type_id": item.tournament_type.id,
                }
                for item in plan_view.tournaments
            ]
        )
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=1,
                    date=date(2026, 8, 14),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.create_weekly_schedule(100, plan)

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())
        assert len(tournaments) == 1
        assert tournaments[0].date == date(2026, 8, 14)
    finally:
        await engine.dispose()


async def test_created_weekly_schedule_reads_created_tournaments(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "schedule.db")
    try:
        await seed_calendar_data(session_factory)
        plan_view = await service.build_next_week_plan(100)
        plan = WeeklyTournamentPlan.from_fsm(
            [
                {
                    "date": item.date.isoformat(),
                    "tournament_type_id": item.tournament_type.id,
                }
                for item in plan_view.tournaments
            ]
        )
        await service.create_weekly_schedule(100, plan)

        schedule = await TournamentScheduleService(session_factory).get_created_weekly_schedule(
            100,
            plan,
        )

        assert len(schedule.tournaments) == 5
        assert schedule.tournaments[0].tournament_type_name == "Баунти турнир"
        assert schedule.tournaments[-1].date == date(2026, 8, 16)
    finally:
        await engine.dispose()


async def test_player_cannot_build_weekly_plan(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "access.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add(
                build_player(
                    telegram_id=200,
                    display_name="Player",
                    status=UserStatus.ACTIVE,
                    role=UserRole.PLAYER,
                )
            )
            await session.commit()

        with pytest.raises(AdminAccessDeniedError):
            await service.build_next_week_plan(200)
    finally:
        await engine.dispose()


def test_stale_fsm_plan_is_rejected() -> None:
    with pytest.raises(CalendarPlanStaleError):
        WeeklyTournamentPlan.from_fsm(None)


def test_plan_validation_requires_five_playing_days() -> None:
    with pytest.raises(CalendarWeeklyPlanIntegrityError):
        WeeklyTournamentPlan.from_fsm(
            [
                {"date": "2026-08-12", "tournament_type_id": 1},
                {"date": "2026-08-14", "tournament_type_id": 3},
                {"date": "2026-08-16", "tournament_type_id": 5},
            ]
        )
