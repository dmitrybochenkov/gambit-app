from datetime import date, datetime
from pathlib import Path

import pytest
from conftest import (
    build_player,
    seed_tournament_configs_async,
    seed_tournament_rules_async,
    seed_tournament_types_async,
    seed_weekly_templates_async,
    tournament_type_id,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.common.clock import FixedClock
from app.db.base import Base
from app.db.models import (
    ScoringConfig,
    Season,
    Tournament,
    TournamentEconomyConfig,
    TournamentRebuyConfig,
    TournamentRegistration,
    TournamentType,
    TournamentTypeRule,
    User,
    WeeklyTournamentTemplate,
)
from app.db.models.enums import TournamentStatus, UserRole, UserStatus
from app.services.access_policy import AdminAccessDeniedError
from app.services.season_service import SeasonService
from app.services.tournament_planning_service import (
    CalendarPlanStaleError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentNotEditableError,
    CalendarTournamentTypeNotFoundError,
    CalendarWeeklyPlanIntegrityError,
    TournamentPlanningService,
    WeeklyPlanningStatus,
    WeeklyTournamentPlan,
    next_complete_game_week,
)
from app.services.tournament_schedule_service import TournamentScheduleService
from app.services.tournament_service import TournamentService


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
        await seed_tournament_rules_async(session)
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
            "Bounty",
            "Classic",
            "Freezeout",
            "Deep Stack",
            "Boss Bounty",
        ]
    finally:
        await engine.dispose()


async def test_calendar_type_options_include_only_creatable_formats(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "creatable.db")
    try:
        await seed_calendar_data(session_factory)

        options = await service.list_calendar_tournament_type_options(100)

        assert [option.code for option in options] == [
            "mystery_bounty",
            "boss_bounty",
            "bounty_v2",
            "classic_v2",
            "freezeout_v2",
            "deep_stack",
            "white_party",
        ]
    finally:
        await engine.dispose()


async def test_calendar_create_rejects_historical_non_creatable_type(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "historical.db")
    try:
        await seed_calendar_data(session_factory)

        with pytest.raises(CalendarTournamentTypeNotFoundError):
            await service.create_calendar_tournament(
                100,
                tournament_date=date(2026, 8, 12),
                tournament_type_id=tournament_type_id("bounty"),
            )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())
        assert tournaments == []
    finally:
        await engine.dispose()


async def test_versioned_format_configs_preserve_historical_rows(tmp_path: Path) -> None:
    _service, session_factory, engine = await create_planning_service(tmp_path / "formats.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            types = {
                item.code: item
                for item in (
                    await session.execute(select(TournamentType).order_by(TournamentType.id))
                ).scalars()
            }
            economies = {
                item.tournament_type_id: item
                for item in (await session.execute(select(TournamentEconomyConfig))).scalars()
            }
            rebuys_by_type: dict[int, list[TournamentRebuyConfig]] = {}
            for rebuy in (
                await session.execute(
                    select(TournamentRebuyConfig).order_by(
                        TournamentRebuyConfig.tournament_type_id,
                        TournamentRebuyConfig.rebuy_order,
                    )
                )
            ).scalars():
                rebuys_by_type.setdefault(rebuy.tournament_type_id, []).append(rebuy)
            rules = {
                item.tournament_type_id: item
                for item in (await session.execute(select(TournamentTypeRule))).scalars()
            }

        assert types["bounty"].is_creatable is False
        assert types["classic"].is_creatable is False
        assert types["freezeout"].is_creatable is False
        assert types["double_double"].is_creatable is False
        assert types["mystery_bounty"].is_creatable is True
        assert types["boss_bounty"].is_creatable is True

        bounty = economies[types["bounty"].id]
        bounty_v2 = economies[types["bounty_v2"].id]
        assert (
            bounty_v2.entry_fee,
            bounty_v2.entry_stack,
            bounty_v2.addon_fee,
            bounty_v2.addon_stack,
        ) == (
            bounty.entry_fee,
            bounty.entry_stack,
            bounty.addon_fee,
            bounty.addon_stack,
        )
        assert [
            (rebuy.rebuy_order, rebuy.fee, rebuy.stack)
            for rebuy in rebuys_by_type[types["bounty"].id]
        ] == [
            (1, 600, 30_000),
            (2, 800, 50_000),
            (3, 800, 70_000),
            (4, 800, 90_000),
            (5, 1000, 100_000),
            (6, 1000, 100_000),
        ]
        assert [
            (rebuy.rebuy_order, rebuy.fee, rebuy.stack)
            for rebuy in rebuys_by_type[types["bounty_v2"].id]
        ] == [
            (1, 800, 30_000),
            (2, 800, 50_000),
            (3, 800, 70_000),
            (4, 800, 90_000),
            (5, 1000, 100_000),
            (6, 1000, 100_000),
        ]
        assert rules[types["bounty_v2"].id].knockout_mode == rules[types["bounty"].id].knockout_mode
        assert (
            rules[types["bounty_v2"].id].points_multiplier
            == rules[types["bounty"].id].points_multiplier
        )
        assert types["bounty_v2"].description == types["bounty"].description

        classic = economies[types["classic"].id]
        classic_v2 = economies[types["classic_v2"].id]
        assert (
            classic_v2.entry_fee,
            classic_v2.entry_stack,
            classic_v2.addon_fee,
            classic_v2.addon_stack,
        ) == (
            600,
            classic.entry_stack,
            classic.addon_fee,
            classic.addon_stack,
        )
        assert [
            (rebuy.rebuy_order, rebuy.fee, rebuy.stack)
            for rebuy in rebuys_by_type[types["classic"].id]
        ] == [
            (1, 600, 30_000),
            (2, 800, 50_000),
            (3, 800, 70_000),
            (4, 800, 90_000),
            (5, 1000, 100_000),
            (6, 1000, 100_000),
        ]
        assert [
            (rebuy.rebuy_order, rebuy.fee, rebuy.stack)
            for rebuy in rebuys_by_type[types["classic_v2"].id]
        ] == [
            (1, 800, 30_000),
            (2, 800, 50_000),
            (3, 800, 70_000),
            (4, 800, 90_000),
            (5, 1000, 100_000),
            (6, 1000, 100_000),
        ]
        assert (
            rules[types["classic_v2"].id].knockout_mode == rules[types["classic"].id].knockout_mode
        )
        assert (
            rules[types["classic_v2"].id].points_multiplier
            == rules[types["classic"].id].points_multiplier
        )
        assert types["classic_v2"].description == types["classic"].description

        assert "На этот турнир не действуют привилегии клуба." in str(
            types["freezeout_v2"].description
        )
        assert "На этот турнир не действуют привилегии клуба." not in str(
            types["freezeout"].description
        )

        assert (
            economies[types["deep_stack"].id].entry_stack
            == economies[types["double_double"].id].entry_stack
        )
        assert rules[types["double_double"].id].points_multiplier == 2
        assert rules[types["deep_stack"].id].points_multiplier == 1

        assert economies[types["white_party"].id].entry_fee == 800
        assert economies[types["white_party"].id].entry_stack == 30_000
        assert [(rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["white_party"].id]] == [
            (800, 40_000),
            (800, 50_000),
            (1000, 80_000),
            (1000, 100_000),
        ]
        assert economies[types["white_party"].id].addon_fee == 1000
        assert economies[types["white_party"].id].addon_stack == 150_000
        assert "Приди в белом — получи фишки к стеку." in str(types["white_party"].description)
        assert "10 000" not in str(types["white_party"].description)
    finally:
        await engine.dispose()


async def test_deep_stack_guarantee_is_description_not_actual_tournament_fund(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "deep-stack.db")
    try:
        await seed_calendar_data(session_factory)

        tournament = await service.create_calendar_tournament(
            100,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("deep_stack"),
        )

        async with session_factory() as session:
            stored = await session.get(Tournament, tournament.id)
            deep_stack = await session.get(TournamentType, tournament_type_id("deep_stack"))

        assert stored is not None
        assert stored.tournament_fund is None
        assert deep_stack is not None
        assert deep_stack.description == "Гарантированный фонд турнира — 2500 очков."
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


async def test_weekly_plan_uses_rotation_fallback_when_sunday_was_skipped(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "skipped.db")
    try:
        await seed_calendar_data(session_factory)
        await seed_week_tournaments(
            session_factory,
            dates=[
                date(2026, 8, 6),
                date(2026, 8, 7),
                date(2026, 8, 8),
            ],
            status=TournamentStatus.CLOSED,
        )

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
            tournament_type_id("freezeout_v2"),
        )

        assert [item.tournament_type.name for item in updated.tournaments] == [
            "Bounty",
            "Freezeout",
            "Freezeout",
            "Deep Stack",
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
        assert empty.status == WeeklyPlanningStatus.READY
        assert empty.plan is not None
        assert len(empty.plan.tournaments) == 5

        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 12)],
            status=TournamentStatus.ACTIVE,
        )

        in_progress = await service.inspect_next_week(100)
        assert in_progress.status == WeeklyPlanningStatus.BLOCKED_BY_ACTIVE_WEEK
        assert in_progress.schedule is not None
        assert [item.date for item in in_progress.schedule.tournaments] == [date(2026, 8, 12)]
        assert in_progress.schedule.tournaments[0].tournament_type_name == "Баунти турнир"
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

            assert planning.status == WeeklyPlanningStatus.BLOCKED_BY_ACTIVE_WEEK
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


async def test_superadmin_tournament_hub_counts_active_on_or_before_tournament_day(
    tmp_path: Path,
) -> None:
    _, session_factory, engine = await create_planning_service(tmp_path / "hub-count.db")
    try:
        await seed_calendar_data(session_factory)
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 12), date(2026, 8, 13)],
            status=TournamentStatus.ACTIVE,
        )
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 11)],
            status=TournamentStatus.CLOSED,
        )
        before_day_start = TournamentPlanningService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 13, 10)),
            tournament_day_start_hour=11,
        )
        after_day_start = TournamentPlanningService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 13, 11)),
            tournament_day_start_hour=11,
        )

        before = await before_day_start.get_superadmin_tournament_hub(100)
        after = await after_day_start.get_superadmin_tournament_hub(100)

        assert before.open_tournaments_count == 1
        assert after.open_tournaments_count == 2
    finally:
        await engine.dispose()


async def test_superadmin_open_tournament_list_filters_and_sorts_by_business_day(
    tmp_path: Path,
) -> None:
    _, session_factory, engine = await create_planning_service(tmp_path / "open-list.db")
    try:
        await seed_calendar_data(session_factory)
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 12), date(2026, 8, 13)],
            status=TournamentStatus.ACTIVE,
        )
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 11)],
            status=TournamentStatus.CLOSED,
        )
        service = TournamentPlanningService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 13, 12)),
            tournament_day_start_hour=11,
        )

        page = await service.list_open_tournaments_for_superadmin(100, page=0)

        assert [item.tournament.date for item in page.items] == [
            date(2026, 8, 13),
            date(2026, 8, 12),
        ]
    finally:
        await engine.dispose()


async def test_superadmin_open_tournament_list_requires_superadmin(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "open-auth.db")
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
            await service.list_open_tournaments_for_superadmin(200, page=0)
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

        assert planning.status == WeeklyPlanningStatus.READY
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


async def test_finished_latest_week_with_only_thursday_and_saturday_allows_next_week(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "thu-sat.db")
    try:
        await seed_calendar_data(session_factory)
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 13), date(2026, 8, 15)],
            status=TournamentStatus.CLOSED,
        )

        planning = await service.inspect_next_week(100)

        assert planning.status == WeeklyPlanningStatus.READY
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

        assert planning.status == WeeklyPlanningStatus.READY
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

        assert planning.status == WeeklyPlanningStatus.BLOCKED_BY_ACTIVE_WEEK
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
        assert {item.registration_open for item in tournaments} == {False}
    finally:
        await engine.dispose()


async def test_calendar_autofill_creates_unapproved_week_and_approval_opens_registration(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "approval.db")
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

        preview = await service.create_calendar_autofill_week(
            100,
            year=2026,
            month=8,
            row_number=3,
        )

        assert [item.tournament_date for item in preview.tournaments] == [
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 15),
            date(2026, 8, 16),
        ]
        assert (
            await TournamentService(session_factory).get_registration_options_for_player(
                200,
                from_date=date(2026, 8, 12),
            )
            == []
        )

        approved = await service.approve_calendar_week(
            100,
            year=2026,
            month=8,
            row_number=3,
        )

        assert [item.date for item in approved.tournaments] == [
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 15),
            date(2026, 8, 16),
        ]
        options = await TournamentService(session_factory).get_registration_options_for_player(
            200,
            from_date=date(2026, 8, 12),
        )
        assert [item.date for item in options] == [
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 15),
            date(2026, 8, 16),
        ]
    finally:
        await engine.dispose()


async def test_repeated_calendar_create_callback_does_not_duplicate_tournament(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "stale-date.db")
    try:
        await seed_calendar_data(session_factory)

        await service.create_calendar_tournament(
            100,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("classic_v2"),
        )
        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.create_calendar_tournament(
                100,
                tournament_date=date(2026, 8, 12),
                tournament_type_id=tournament_type_id("freezeout_v2"),
            )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())
        assert len(tournaments) == 1
        assert tournaments[0].date == date(2026, 8, 12)
        assert tournaments[0].tournament_type_id == tournament_type_id("classic_v2")
    finally:
        await engine.dispose()


async def test_calendar_autofill_rejects_partial_month_boundary_week(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "boundary.db")
    try:
        await seed_calendar_data(session_factory)

        with pytest.raises(CalendarWeeklyPlanIntegrityError):
            await service.get_calendar_autofill_preview(
                100,
                year=2026,
                month=8,
                row_number=1,
            )
    finally:
        await engine.dispose()


async def test_week_approval_only_opens_unapproved_tournaments_and_can_be_repeated(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "late-add.db")
    try:
        await seed_calendar_data(session_factory)
        await service.create_calendar_tournament(
            100,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("bounty_v2"),
        )
        await service.approve_calendar_week(100, year=2026, month=8, row_number=3)

        await service.create_calendar_tournament(
            100,
            tournament_date=date(2026, 8, 13),
            tournament_type_id=tournament_type_id("classic_v2"),
        )
        async with session_factory() as session:
            before = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )
        assert [(item.date, item.registration_open) for item in before] == [
            (date(2026, 8, 12), True),
            (date(2026, 8, 13), False),
        ]

        approved = await service.approve_calendar_week(100, year=2026, month=8, row_number=3)

        assert [item.date for item in approved.tournaments] == [date(2026, 8, 13)]
        async with session_factory() as session:
            after = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )
        assert [(item.date, item.registration_open) for item in after] == [
            (date(2026, 8, 12), True),
            (date(2026, 8, 13), True),
        ]
    finally:
        await engine.dispose()


async def test_calendar_type_change_preserves_date_and_registration_open(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "type-change.db")
    try:
        await seed_calendar_data(session_factory)
        tournament = await service.create_calendar_tournament(
            100,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("bounty_v2"),
        )

        changed = await service.change_calendar_tournament_type(
            100,
            tournament_id=tournament.id,
            new_tournament_type_id=tournament_type_id("freezeout_v2"),
        )

        assert changed.date == date(2026, 8, 12)
        assert changed.tournament_type_id == tournament_type_id("freezeout_v2")
        assert changed.registration_open is False
    finally:
        await engine.dispose()


async def test_calendar_delete_rejects_current_and_closed_tournaments_service_side(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "delete.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            current = Tournament(
                season_id=1,
                tournament_type_id=tournament_type_id("classic_v2"),
                date=date(2026, 8, 8),
                status=TournamentStatus.ACTIVE,
            )
            closed = Tournament(
                season_id=1,
                tournament_type_id=tournament_type_id("classic_v2"),
                date=date(2026, 8, 12),
                tournament_fund=10,
                status=TournamentStatus.CLOSED,
            )
            session.add_all([current, closed])
            await session.commit()
            current_id = current.id
            closed_id = closed.id

        with pytest.raises(CalendarTournamentNotEditableError):
            await service.delete_calendar_tournament(100, tournament_id=current_id)
        with pytest.raises(CalendarTournamentNotEditableError):
            await service.delete_calendar_tournament(100, tournament_id=closed_id)
    finally:
        await engine.dispose()


async def test_calendar_delete_removes_registrations_but_keeps_users(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "delete-reg.db")
    try:
        await seed_calendar_data(session_factory)
        tournament = await service.create_calendar_tournament(
            100,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("classic_v2"),
        )
        async with session_factory() as session:
            player = build_player(
                telegram_id=200,
                display_name="Player",
                status=UserStatus.ACTIVE,
                role=UserRole.PLAYER,
            )
            session.add(player)
            await session.flush()
            session.add(
                TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=player.id,
                )
            )
            await session.commit()
            player_id = player.id

        deleted, notifications = await service.delete_calendar_tournament(
            100,
            tournament_id=tournament.id,
        )

        assert deleted.id == tournament.id
        assert [item.telegram_id for item in notifications] == [200]
        async with session_factory() as session:
            assert await session.get(Tournament, tournament.id) is None
            assert await session.get(User, player_id) is not None
            registrations = list((await session.execute(select(TournamentRegistration))).scalars())
        assert registrations == []
    finally:
        await engine.dispose()


async def test_calendar_tournament_uses_season_for_its_own_date_after_boundary_change(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "season.db")
    try:
        await seed_calendar_data(session_factory)
        await SeasonService(
            session_factory,
            clock=FixedClock(datetime(2026, 8, 9)),
        ).create_next_season(
            100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
        )

        august = await service.create_calendar_tournament(
            100,
            tournament_date=date(2026, 8, 26),
            tournament_type_id=tournament_type_id("classic_v2"),
        )
        september = await service.create_calendar_tournament(
            100,
            tournament_date=date(2026, 9, 2),
            tournament_type_id=tournament_type_id("classic_v2"),
        )

        async with session_factory() as session:
            august_tournament = await session.get(Tournament, august.id)
            september_tournament = await session.get(Tournament, september.id)
        assert august_tournament is not None
        assert september_tournament is not None
        assert august_tournament.season_id == 1
        assert september_tournament.season_id != august_tournament.season_id
    finally:
        await engine.dispose()


async def test_create_weekly_schedule_allows_removed_day(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "removed-day.db")
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
        ).without_date(date(2026, 8, 15))

        created = await service.create_weekly_schedule(100, plan)

        assert [item.date for item in created.tournaments] == [
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 16),
        ]
        async with session_factory() as session:
            tournaments = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )
        assert [item.date for item in tournaments] == [
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 16),
        ]
    finally:
        await engine.dispose()


async def test_created_week_is_unaffected_by_template_changes(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(
        tmp_path / "template-change.db"
    )
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
        ).without_date(date(2026, 8, 15))
        await service.create_weekly_schedule(100, plan)

        async with session_factory() as session:
            templates = list((await session.execute(select(WeeklyTournamentTemplate))).scalars())
            for template in templates:
                template.is_active = False
            await session.commit()

        planning = await service.inspect_next_week(100)

        assert planning.status == WeeklyPlanningStatus.BLOCKED_BY_ACTIVE_WEEK
        assert planning.schedule is not None
        assert [item.date for item in planning.schedule.tournaments] == [
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 16),
        ]
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
        assert schedule.tournaments[0].tournament_type_name == "Bounty"
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


def test_plan_validation_allows_partial_week_but_rejects_invalid_dates() -> None:
    plan = WeeklyTournamentPlan.from_fsm(
        [
            {"date": "2026-08-12", "tournament_type_id": 1},
            {"date": "2026-08-14", "tournament_type_id": 3},
            {"date": "2026-08-16", "tournament_type_id": 5},
        ]
    )
    assert plan.dates == (
        date(2026, 8, 12),
        date(2026, 8, 14),
        date(2026, 8, 16),
    )

    with pytest.raises(CalendarWeeklyPlanIntegrityError):
        WeeklyTournamentPlan.from_fsm(
            [
                {"date": "2026-08-12", "tournament_type_id": 1},
                {"date": "2026-08-19", "tournament_type_id": 3},
            ]
        )
