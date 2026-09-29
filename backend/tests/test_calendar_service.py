from datetime import date, datetime, timedelta
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
from sqlalchemy.exc import IntegrityError
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
    TournamentResult,
    TournamentType,
    TournamentTypeRule,
    User,
    WeeklyTournamentTemplate,
)
from app.db.models.enums import (
    KnockoutMode,
    TournamentResultSource,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.services.access_policy import AdminAccessDeniedError
from app.services.dto.tournaments import (
    TournamentCalendarDraftCommand,
    TournamentCalendarDraftItem,
)
from app.services.season_service import SeasonService
from app.services.tournament_planning_service import (
    CalendarAutofillDraftInvalidError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentNotEditableError,
    CalendarTournamentTypeNotFoundError,
    CalendarWeeklyPlanIntegrityError,
    CalendarWeekNotEmptyError,
    TournamentPlanningService,
    WeeklyTemplateInvalidError,
    WeeklyTemplateTournamentTypeNotAllowedError,
)
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
        await session.execute(WeeklyTournamentTemplate.__table__.delete())
        session.add_all(
            [
                WeeklyTournamentTemplate(
                    weekday=2,
                    tournament_type_id=tournament_type_id("bounty_v3"),
                ),
                WeeklyTournamentTemplate(
                    weekday=3,
                    tournament_type_id=tournament_type_id("classic_v3"),
                ),
                WeeklyTournamentTemplate(
                    weekday=4,
                    tournament_type_id=tournament_type_id("freezeout_v2"),
                ),
                WeeklyTournamentTemplate(
                    weekday=5,
                    tournament_type_id=tournament_type_id("deep_stack_v2"),
                ),
                WeeklyTournamentTemplate(
                    weekday=6,
                    tournament_type_id=tournament_type_id("mystery_bounty"),
                    rotation_order=1,
                ),
                WeeklyTournamentTemplate(
                    weekday=6,
                    tournament_type_id=tournament_type_id("boss_bounty"),
                    rotation_order=2,
                ),
            ]
        )
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
                    scoring_config_id=1,
                    tournament_type_id=tournament_type_id,
                    date=tournament_date,
                    tournament_fund=10 if status == TournamentStatus.CLOSED else None,
                    status=status,
                )
                for tournament_date in dates
            ]
        )
        await session.commit()


@pytest.mark.parametrize("row_number", [0, -1, 99])
async def test_calendar_week_rejects_out_of_range_rows(
    tmp_path: Path,
    row_number: int,
) -> None:
    service, session_factory, engine = await create_planning_service(
        tmp_path / f"calendar-row-{row_number}.db"
    )
    try:
        await seed_calendar_data(session_factory)
        with pytest.raises(CalendarWeeklyPlanIntegrityError):
            await service.get_calendar_week(1, year=2026, month=8, row_number=row_number)
    finally:
        await engine.dispose()


async def test_calendar_autofill_draft_creates_exact_edited_plan_without_recomputing_template(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "draft.db")
    try:
        await seed_calendar_data(session_factory)
        preview = await service.get_calendar_autofill_preview(1, year=2026, month=8, row_number=3)
        assert preview.week_start == date(2026, 8, 10)
        assert preview.week_end == date(2026, 8, 16)

        await service.replace_weekly_template(
            1,
            tournament_type_ids_by_weekday={
                0: (tournament_type_id("month_main"),),
            },
        )
        command = TournamentCalendarDraftCommand(
            year=2026,
            month=8,
            row_number=3,
            tournaments=(
                TournamentCalendarDraftItem(
                    tournament_date=date(2026, 8, 12),
                    tournament_type_id=tournament_type_id("classic_v3"),
                ),
                TournamentCalendarDraftItem(
                    tournament_date=date(2026, 8, 15),
                    tournament_type_id=tournament_type_id("freezeout_v2"),
                ),
            ),
        )

        created = await service.create_calendar_autofill_draft(1, command)

        assert [
            (item.tournament_date, item.tournament_type.code) for item in created.tournaments
        ] == [
            (date(2026, 8, 12), "classic_v3"),
            (date(2026, 8, 15), "freezeout_v2"),
        ]
        async with session_factory() as session:
            rows = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )
            template_rows = list(
                (
                    await session.execute(
                        select(WeeklyTournamentTemplate).order_by(
                            WeeklyTournamentTemplate.weekday,
                            WeeklyTournamentTemplate.rotation_order,
                        )
                    )
                ).scalars()
            )
        assert [(row.date, row.tournament_type_id) for row in rows] == [
            (date(2026, 8, 12), tournament_type_id("classic_v3")),
            (date(2026, 8, 15), tournament_type_id("freezeout_v2")),
        ]
        assert [(row.weekday, row.tournament_type_id) for row in template_rows] == [
            (0, tournament_type_id("month_main")),
        ]
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "items",
    [
        (),
        (
            TournamentCalendarDraftItem(
                tournament_date=date(2026, 8, 12),
                tournament_type_id=tournament_type_id("classic_v3"),
            ),
            TournamentCalendarDraftItem(
                tournament_date=date(2026, 8, 12),
                tournament_type_id=tournament_type_id("freezeout_v2"),
            ),
        ),
        (
            TournamentCalendarDraftItem(
                tournament_date=date(2026, 8, 20),
                tournament_type_id=tournament_type_id("classic_v3"),
            ),
        ),
    ],
)
async def test_calendar_autofill_draft_rejects_invalid_collection(
    tmp_path: Path,
    items: tuple[TournamentCalendarDraftItem, ...],
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "invalid-draft.db")
    try:
        await seed_calendar_data(session_factory)
        command = TournamentCalendarDraftCommand(
            year=2026,
            month=8,
            row_number=3,
            tournaments=items,
        )
        with pytest.raises(CalendarAutofillDraftInvalidError):
            await service.create_calendar_autofill_draft(1, command)
        async with session_factory() as session:
            assert list((await session.execute(select(Tournament))).scalars()) == []
    finally:
        await engine.dispose()


async def test_calendar_autofill_draft_revalidates_type_and_week_occupancy(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "stale-draft.db")
    try:
        await seed_calendar_data(session_factory)
        item = TournamentCalendarDraftItem(
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("classic_v3"),
        )
        command = TournamentCalendarDraftCommand(
            year=2026,
            month=8,
            row_number=3,
            tournaments=(item,),
        )
        unknown_command = TournamentCalendarDraftCommand(
            year=2026,
            month=8,
            row_number=3,
            tournaments=(
                TournamentCalendarDraftItem(
                    tournament_date=date(2026, 8, 12),
                    tournament_type_id=999_999,
                ),
            ),
        )
        with pytest.raises(CalendarTournamentTypeNotFoundError):
            await service.create_calendar_autofill_draft(1, unknown_command)
        async with session_factory() as session:
            tournament_type = await session.get(TournamentType, item.tournament_type_id)
            assert tournament_type is not None
            tournament_type.is_creatable = False
            await session.commit()
        with pytest.raises(CalendarTournamentTypeNotFoundError):
            await service.create_calendar_autofill_draft(1, command)

        async with session_factory() as session:
            tournament_type = await session.get(TournamentType, item.tournament_type_id)
            assert tournament_type is not None
            tournament_type.is_creatable = True
            season = (await session.execute(select(Season))).scalars().first()
            assert season is not None
            session.add(
                Tournament(
                    season_id=season.id,
                    tournament_type_id=tournament_type_id("freezeout_v2"),
                    scoring_config_id=season.scoring_config_id,
                    date=date(2026, 8, 14),
                    status=TournamentStatus.ACTIVE,
                    registration_open=False,
                )
            )
            await session.commit()
        with pytest.raises(CalendarWeekNotEmptyError):
            await service.create_calendar_autofill_draft(1, command)
        async with session_factory() as session:
            rows = list((await session.execute(select(Tournament))).scalars())
        assert [row.date for row in rows] == [date(2026, 8, 14)]
    finally:
        await engine.dispose()


async def test_calendar_autofill_draft_maps_concurrent_unique_conflict_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "unique-draft.db")
    try:
        await seed_calendar_data(session_factory)
        command = TournamentCalendarDraftCommand(
            year=2026,
            month=8,
            row_number=3,
            tournaments=(
                TournamentCalendarDraftItem(
                    tournament_date=date(2026, 8, 12),
                    tournament_type_id=tournament_type_id("classic_v3"),
                ),
            ),
        )

        async def fail_with_unique(
            _repository: TournamentRepository,
            _tournament: Tournament,
        ) -> Tournament:
            raise IntegrityError("INSERT", {}, Exception("unique date"))

        monkeypatch.setattr(TournamentRepository, "add", fail_with_unique)
        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.create_calendar_autofill_draft(1, command)
        async with session_factory() as session:
            assert list((await session.execute(select(Tournament))).scalars()) == []
    finally:
        await engine.dispose()


async def test_calendar_autofill_draft_authorizes_and_rolls_back_as_one_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "atomic-draft.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            player = build_player(
                telegram_id=200,
                display_name="Player",
                status=UserStatus.ACTIVE,
                role=UserRole.PLAYER,
            )
            session.add(player)
            await session.commit()
            player_id = player.id
        command = TournamentCalendarDraftCommand(
            year=2026,
            month=8,
            row_number=3,
            tournaments=(
                TournamentCalendarDraftItem(
                    tournament_date=date(2026, 8, 12),
                    tournament_type_id=tournament_type_id("classic_v3"),
                ),
                TournamentCalendarDraftItem(
                    tournament_date=date(2026, 8, 14),
                    tournament_type_id=tournament_type_id("freezeout_v2"),
                ),
            ),
        )
        with pytest.raises(AdminAccessDeniedError):
            await service.create_calendar_autofill_draft(player_id, command)

        original_add = TournamentRepository.add
        calls = 0

        async def fail_second_add(
            repository: TournamentRepository,
            tournament: Tournament,
        ) -> Tournament:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("forced failure")
            return await original_add(repository, tournament)

        monkeypatch.setattr(TournamentRepository, "add", fail_second_add)
        with pytest.raises(RuntimeError, match="forced failure"):
            await service.create_calendar_autofill_draft(1, command)
        async with session_factory() as session:
            assert list((await session.execute(select(Tournament))).scalars()) == []
    finally:
        await engine.dispose()


async def test_future_type_change_rejects_existing_fact_data(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(
        tmp_path / "future-type-facts.db"
    )
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            player = build_player(telegram_id=200, display_name="Player")
            session.add(player)
            await session.flush()
            tournament = Tournament(
                season_id=1,
                scoring_config_id=1,
                tournament_type_id=tournament_type_id("classic_v3"),
                date=date(2026, 8, 12),
                status=TournamentStatus.ACTIVE,
            )
            session.add(tournament)
            await session.flush()
            session.add(
                TournamentResult(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_by_user_id=1,
                )
            )
            await session.commit()
            tournament_id = tournament.id
            original_type_id = tournament.tournament_type_id

        with pytest.raises(CalendarTournamentNotEditableError):
            await service.change_calendar_tournament_type(
                1,
                tournament_id=tournament_id,
                new_tournament_type_id=tournament_type_id("bounty_v3"),
            )

        async with session_factory() as session:
            tournament = await session.get(Tournament, tournament_id)
            assert tournament is not None
            assert tournament.tournament_type_id == original_type_id
    finally:
        await engine.dispose()


async def test_calendar_month_uses_db_calendar_codes_and_month_type_order(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(
        tmp_path / "calendar_codes.db",
        today=date(2026, 9, 1),
    )
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    Tournament(
                        season_id=1,
                        scoring_config_id=1,
                        tournament_type_id=tournament_type_id("classic_v3"),
                        date=date(2026, 8, 31),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        scoring_config_id=1,
                        tournament_type_id=tournament_type_id("deep_stack"),
                        date=date(2026, 9, 5),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        scoring_config_id=1,
                        tournament_type_id=tournament_type_id("bounty_v3"),
                        date=date(2026, 9, 6),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        scoring_config_id=1,
                        tournament_type_id=tournament_type_id("deep_stack"),
                        date=date(2026, 9, 12),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        scoring_config_id=1,
                        tournament_type_id=tournament_type_id("boss_bounty"),
                        date=date(2026, 10, 1),
                        status=TournamentStatus.ACTIVE,
                    ),
                ]
            )
            await session.commit()

        view = await service.get_calendar_month(1, year=2026, month=9)

        assert [(item.name, item.calendar_code) for item in view.tournament_types] == [
            ("Deep Stack", "D"),
            ("Bounty", "B3"),
        ]
        september_codes = [
            day.tournament.tournament_type_calendar_code
            for week in view.weeks
            for day in week.days
            if day.in_month and day.tournament is not None
        ]
        assert september_codes == ["D", "B3", "D"]
    finally:
        await engine.dispose()


async def test_calendar_format_detail_is_restricted_to_selected_month(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(
        tmp_path / "calendar_format_month.db",
        today=date(2026, 9, 1),
    )
    try:
        await seed_calendar_data(session_factory)
        september_type_id = tournament_type_id("deep_stack")
        october_type_id = tournament_type_id("boss_bounty")
        async with session_factory() as session:
            september_type = await session.get(TournamentType, september_type_id)
            assert september_type is not None
            september_type.short_name = "Дипстек"
            session.add_all(
                [
                    Tournament(
                        season_id=1,
                        scoring_config_id=1,
                        tournament_type_id=september_type_id,
                        date=date(2026, 9, 5),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        scoring_config_id=1,
                        tournament_type_id=october_type_id,
                        date=date(2026, 10, 1),
                        status=TournamentStatus.ACTIVE,
                    ),
                ]
            )
            await session.commit()

        detail = await service.get_calendar_format_detail(
            1,
            year=2026,
            month=9,
            tournament_type_id=september_type_id,
        )

        assert detail.name == "Deep Stack"
        month = await service.get_calendar_month(1, year=2026, month=9)
        assert [(item.calendar_code, item.short_name) for item in month.tournament_types] == [
            ("D", "Дипстек")
        ]
        with pytest.raises(CalendarTournamentTypeNotFoundError):
            await service.get_calendar_format_detail(
                1,
                year=2026,
                month=9,
                tournament_type_id=october_type_id,
            )
    finally:
        await engine.dispose()


async def test_calendar_create_rejects_historical_non_creatable_type(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "historical.db")
    try:
        await seed_calendar_data(session_factory)

        with pytest.raises(CalendarTournamentTypeNotFoundError):
            await service.create_calendar_tournament(
                1,
                tournament_date=date(2026, 8, 12),
                tournament_type_id=tournament_type_id("bounty"),
            )
        with pytest.raises(CalendarTournamentTypeNotFoundError):
            await service.create_calendar_tournament(
                1,
                tournament_date=date(2026, 8, 12),
                tournament_type_id=tournament_type_id("bounty_v2"),
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
        assert types["bounty_v2"].is_creatable is False
        assert types["classic_v2"].is_creatable is False
        assert types["deep_stack"].is_creatable is False
        assert types["bounty_v3"].is_creatable is True
        assert types["classic_v3"].is_creatable is True
        assert types["deep_stack_v2"].is_creatable is True
        assert types["main_ko"].is_creatable is True
        assert types["slow_blinds"].is_creatable is True
        assert types["satellite"].is_creatable is True
        assert types["black_party"].is_creatable is True

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

        bounty_v3 = economies[types["bounty_v3"].id]
        assert (
            bounty_v3.entry_fee,
            bounty_v3.entry_stack,
            bounty_v3.addon_fee,
            bounty_v3.addon_stack,
        ) == (600, 20_000, 800, 125_000)
        assert [(rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["bounty_v3"].id]] == [
            (800, 30_000),
            (800, 50_000),
            (800, 60_000),
            (1000, 80_000),
            (1000, 80_000),
        ]
        assert rules[types["bounty_v3"].id].knockout_mode == KnockoutMode.SMALL_BIG

        classic_v3 = economies[types["classic_v3"].id]
        assert types["classic_v3"].code == "classic_v3"
        assert types["classic_v3"].name == "Freeroll"
        assert types["classic_v3"].short_name == "Freeroll"
        assert types["classic_v3"].calendar_code == "FR"
        assert (
            classic_v3.entry_fee,
            classic_v3.entry_stack,
            classic_v3.addon_fee,
            classic_v3.addon_stack,
        ) == (0, 15_000, 800, 125_000)
        assert [(rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["classic_v3"].id]] == [
            (800, 30_000),
            (800, 50_000),
            (800, 60_000),
            (1000, 80_000),
            (1000, 80_000),
        ]
        assert rules[types["classic_v3"].id].knockout_mode == KnockoutMode.NONE

        deep_stack_v2 = economies[types["deep_stack_v2"].id]
        assert (
            deep_stack_v2.entry_fee,
            deep_stack_v2.entry_stack,
            deep_stack_v2.addon_fee,
            deep_stack_v2.addon_stack,
        ) == (800, 40_000, 800, 150_000)
        assert [
            (rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["deep_stack_v2"].id]
        ] == [
            (800, 50_000),
            (800, 70_000),
            (1000, 90_000),
            (1000, 90_000),
            (1000, 100_000),
        ]
        assert rules[types["deep_stack_v2"].id].knockout_mode == KnockoutMode.NONE

        main_ko = economies[types["main_ko"].id]
        assert (
            main_ko.entry_fee,
            main_ko.entry_stack,
            main_ko.addon_fee,
            main_ko.addon_stack,
        ) == (800, 30_000, 1000, 150_000)
        assert [(rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["main_ko"].id]] == [
            (1000, 40_000),
            (1000, 60_000),
        ]
        assert rules[types["main_ko"].id].knockout_mode == KnockoutMode.MAIN_KO

        slow_blinds = economies[types["slow_blinds"].id]
        assert types["slow_blinds"].name == "Slow Blinds"
        assert types["slow_blinds"].short_name == "Slow Blinds"
        assert types["slow_blinds"].calendar_code == "SB"
        assert (
            slow_blinds.entry_fee,
            slow_blinds.entry_stack,
            slow_blinds.addon_fee,
            slow_blinds.addon_stack,
        ) == (800, 30_000, 800, 60_000)
        assert [(rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["slow_blinds"].id]] == [
            (800, 30_000),
        ]
        assert rules[types["slow_blinds"].id].knockout_mode == KnockoutMode.NONE

        satellite = economies[types["satellite"].id]
        assert types["satellite"].code == "satellite"
        assert types["satellite"].name == "Satellite"
        assert types["satellite"].short_name == "Satellite"
        assert types["satellite"].calendar_code == "ST"
        assert (
            satellite.entry_fee,
            satellite.entry_stack,
            satellite.addon_fee,
            satellite.addon_stack,
        ) == (800, 30_000, 1000, 150_000)
        assert [(rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["satellite"].id]] == [
            (1000, 50_000),
            (1000, 70_000),
        ]
        assert "1 и 2 место" in str(types["satellite"].description)
        assert rules[types["satellite"].id].knockout_mode == KnockoutMode.NONE
        assert rules[types["satellite"].id].points_multiplier == 1
        assert rules[types["satellite"].id].prize_place_multiplier == 1

        black_party = economies[types["black_party"].id]
        assert types["black_party"].name == "Black Party"
        assert types["black_party"].short_name == "Black Party"
        assert types["black_party"].calendar_code == "BP"
        assert (
            black_party.entry_fee,
            black_party.entry_stack,
            black_party.addon_fee,
            black_party.addon_stack,
        ) == (
            economies[types["white_party"].id].entry_fee,
            economies[types["white_party"].id].entry_stack,
            economies[types["white_party"].id].addon_fee,
            economies[types["white_party"].id].addon_stack,
        )
        assert [(rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["black_party"].id]] == [
            (rebuy.fee, rebuy.stack) for rebuy in rebuys_by_type[types["white_party"].id]
        ]
        assert (
            rules[types["black_party"].id].knockout_mode
            == rules[types["white_party"].id].knockout_mode
        )
        assert types["white_party"].name == "White Party Tournament"
        assert types["white_party"].calendar_code == "WP"
    finally:
        await engine.dispose()


async def test_deep_stack_guarantee_is_description_not_actual_tournament_fund(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "deep-stack.db")
    try:
        await seed_calendar_data(session_factory)

        tournament = await service.create_calendar_tournament(
            1,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("deep_stack_v2"),
        )

        async with session_factory() as session:
            stored = await session.get(Tournament, tournament.id)
            season = await session.get(Season, stored.season_id if stored is not None else 0)
            deep_stack = await session.get(TournamentType, tournament_type_id("deep_stack_v2"))

        assert stored is not None
        assert season is not None
        assert stored.scoring_config_id == season.scoring_config_id
        assert stored.tournament_fund is None
        assert deep_stack is not None
        assert deep_stack.description == "Гарантированный фонд турнира — 2500 очков."
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

        before = await before_day_start.get_superadmin_tournament_hub(1)
        after = await after_day_start.get_superadmin_tournament_hub(1)

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

        page = await service.list_open_tournaments_for_superadmin(1, page=0)

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
            await service.list_open_tournaments_for_superadmin(2, page=0)
    finally:
        await engine.dispose()


async def test_calendar_autofill_creates_unapproved_week_and_approval_opens_registration(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "approval.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            player = build_player(
                telegram_id=200,
                display_name="Player",
                status=UserStatus.ACTIVE,
                role=UserRole.PLAYER,
            )
            session.add(player)
            await session.flush()
            player_id = player.id
            await session.commit()

        preview = await service.get_calendar_autofill_preview(
            1,
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
        assert [item.tournament_type.code for item in preview.tournaments] == [
            "bounty_v3",
            "classic_v3",
            "freezeout_v2",
            "deep_stack_v2",
            "boss_bounty",
        ]

        created = await service.create_calendar_autofill_week(
            1,
            year=2026,
            month=8,
            row_number=3,
        )

        assert created == preview
        assert (
            await TournamentService(session_factory).get_registration_options_for_player(
                player_id,
                from_date=date(2026, 8, 12),
            )
            == []
        )

        approved = await service.approve_calendar_week(
            1,
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
            player_id,
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
            1,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("classic_v3"),
        )
        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.create_calendar_tournament(
                1,
                tournament_date=date(2026, 8, 12),
                tournament_type_id=tournament_type_id("freezeout_v2"),
            )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())
        assert len(tournaments) == 1
        assert tournaments[0].date == date(2026, 8, 12)
        assert tournaments[0].tournament_type_id == tournament_type_id("classic_v3")
    finally:
        await engine.dispose()


async def test_calendar_cross_month_week_autofill_and_approval_are_canonical(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "boundary.db")
    try:
        await seed_calendar_data(session_factory)

        september_week = await service.get_calendar_week(1, year=2026, month=9, row_number=5)
        october_week = await service.get_calendar_week(1, year=2026, month=10, row_number=1)
        expected_week_dates = [date(2026, 9, 28) + timedelta(days=offset) for offset in range(7)]

        assert september_week.week_start == october_week.week_start == date(2026, 9, 28)
        assert september_week.week_end == october_week.week_end == date(2026, 10, 4)
        assert [day.date for day in september_week.days] == expected_week_dates
        assert [day.date for day in october_week.days] == expected_week_dates

        september_preview = await service.get_calendar_autofill_preview(
            1, year=2026, month=9, row_number=5
        )
        october_preview = await service.get_calendar_autofill_preview(
            1, year=2026, month=10, row_number=1
        )
        expected_tournament_dates = [
            date(2026, 9, 30),
            date(2026, 10, 1),
            date(2026, 10, 2),
            date(2026, 10, 3),
            date(2026, 10, 4),
        ]
        assert [item.tournament_date for item in september_preview.tournaments] == (
            expected_tournament_dates
        )
        assert october_preview == september_preview

        await service.create_calendar_autofill_week(1, year=2026, month=9, row_number=5)
        with pytest.raises(CalendarWeekNotEmptyError):
            await service.create_calendar_autofill_week(1, year=2026, month=10, row_number=1)

        september = await service.get_calendar_month(1, year=2026, month=9)
        october = await service.get_calendar_month(1, year=2026, month=10)
        assert [
            day.date
            for week in september.weeks
            for day in week.days
            if day.in_month and day.tournament is not None
        ] == [date(2026, 9, 30)]
        assert [
            day.date
            for week in october.weeks
            for day in week.days
            if day.in_month and day.tournament is not None
        ] == expected_tournament_dates[1:]

        approved = await service.approve_calendar_week(1, year=2026, month=10, row_number=1)
        assert [item.date for item in approved.tournaments] == expected_tournament_dates
    finally:
        await engine.dispose()


async def test_calendar_cross_year_week_uses_same_logical_dates(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "year-boundary.db")
    try:
        await seed_calendar_data(session_factory)

        december = await service.get_calendar_week(1, year=2026, month=12, row_number=5)
        january = await service.get_calendar_week(1, year=2027, month=1, row_number=1)

        assert december.week_start == january.week_start == date(2026, 12, 28)
        assert december.week_end == january.week_end == date(2027, 1, 3)
        assert [day.date for day in december.days] == [day.date for day in january.days]
    finally:
        await engine.dispose()


async def test_weekly_template_read_replace_and_order_normalization(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "template.db")
    try:
        await seed_calendar_data(session_factory)
        original = await service.get_weekly_template(1)
        assert original.days[0].tournament_types == ()
        assert len(original.days[6].tournament_types) == 2

        replacement = {
            2: (
                tournament_type_id("classic_v3"),
                tournament_type_id("bounty_v3"),
            ),
            3: (tournament_type_id("freezeout_v2"),),
            6: (
                tournament_type_id("boss_bounty"),
                tournament_type_id("mystery_bounty"),
            ),
        }
        view = await service.replace_weekly_template(
            1,
            tournament_type_ids_by_weekday=replacement,
        )

        assert [item.code for item in view.days[2].tournament_types] == [
            "classic_v3",
            "bounty_v3",
        ]
        async with session_factory() as session:
            rows = await TournamentRepository(session).list_active_weekly_templates()
        assert [(row.weekday, row.rotation_order) for row in rows] == [
            (2, 1),
            (2, 2),
            (3, 1),
            (6, 1),
            (6, 2),
        ]
    finally:
        await engine.dispose()


async def test_weekly_template_validation_is_fail_closed(tmp_path: Path) -> None:
    service, session_factory, engine = await create_planning_service(
        tmp_path / "template-validation.db"
    )
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            player = build_player(
                telegram_id=201,
                display_name="Player",
                status=UserStatus.ACTIVE,
                role=UserRole.PLAYER,
            )
            session.add(player)
            await session.flush()
            player_id = player.id
            await session.commit()
        before = await service.get_weekly_template(1)

        with pytest.raises(AdminAccessDeniedError):
            await service.get_weekly_template(player_id)

        options = await service.list_weekly_template_add_options(
            1,
            selected_tournament_type_ids=(tournament_type_id("bounty_v3"),),
        )
        assert tournament_type_id("bounty_v3") not in {item.id for item in options}
        assert all(item.code != "bounty_v2" for item in options)

        with pytest.raises(WeeklyTemplateInvalidError):
            await service.replace_weekly_template(
                1,
                tournament_type_ids_by_weekday={
                    2: (
                        tournament_type_id("bounty_v3"),
                        tournament_type_id("bounty_v3"),
                    )
                },
            )
        with pytest.raises(WeeklyTemplateTournamentTypeNotAllowedError):
            await service.replace_weekly_template(
                1,
                tournament_type_ids_by_weekday={
                    0: (tournament_type_id("bounty_v2"),),
                },
            )
        with pytest.raises(WeeklyTemplateInvalidError):
            await service.replace_weekly_template(
                1,
                tournament_type_ids_by_weekday={0: (999_999,)},
            )
        with pytest.raises(WeeklyTemplateInvalidError):
            await service.replace_weekly_template(
                1,
                tournament_type_ids_by_weekday={},
            )

        assert await service.get_weekly_template(1) == before
    finally:
        await engine.dispose()


async def test_weekday_rotation_uses_only_matching_history_and_is_independent(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "rotation.db")
    try:
        await seed_calendar_data(session_factory)
        await service.replace_weekly_template(
            1,
            tournament_type_ids_by_weekday={
                2: (
                    tournament_type_id("bounty_v3"),
                    tournament_type_id("classic_v3"),
                ),
                3: (tournament_type_id("freezeout_v2"),),
                6: (
                    tournament_type_id("mystery_bounty"),
                    tournament_type_id("boss_bounty"),
                ),
            },
        )
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 5)],
            status=TournamentStatus.CLOSED,
            tournament_type_id=tournament_type_id("bounty_v3"),
        )
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 12)],
            status=TournamentStatus.CLOSED,
            tournament_type_id=tournament_type_id("deep_stack_v2"),
        )
        await seed_week_tournaments(
            session_factory,
            dates=[date(2026, 8, 9)],
            status=TournamentStatus.CLOSED,
            tournament_type_id=tournament_type_id("mystery_bounty"),
        )

        preview = await service.get_calendar_autofill_preview(1, year=2026, month=8, row_number=4)

        assert [
            (item.tournament_date.weekday(), item.tournament_type.code)
            for item in preview.tournaments
        ] == [
            (2, "classic_v3"),
            (3, "freezeout_v2"),
            (6, "boss_bounty"),
        ]
    finally:
        await engine.dispose()


async def test_weekly_template_replacement_rolls_back_on_repository_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "rollback.db")
    try:
        await seed_calendar_data(session_factory)
        before = await service.get_weekly_template(1)
        original_replace = TournamentRepository.replace_active_weekly_templates

        async def fail_after_replace(
            repository: TournamentRepository,
            rows: list[WeeklyTournamentTemplate],
        ) -> None:
            await original_replace(repository, rows)
            raise RuntimeError("write failed")

        monkeypatch.setattr(
            TournamentRepository,
            "replace_active_weekly_templates",
            fail_after_replace,
        )

        with pytest.raises(RuntimeError, match="write failed"):
            await service.replace_weekly_template(
                1,
                tournament_type_ids_by_weekday={
                    2: (tournament_type_id("classic_v3"),),
                },
            )

        assert await service.get_weekly_template(1) == before
    finally:
        await engine.dispose()


async def test_week_approval_only_opens_unapproved_tournaments_and_can_be_repeated(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "late-add.db")
    try:
        await seed_calendar_data(session_factory)
        await service.create_calendar_tournament(
            1,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("bounty_v3"),
        )
        await service.approve_calendar_week(1, year=2026, month=8, row_number=3)

        await service.create_calendar_tournament(
            1,
            tournament_date=date(2026, 8, 13),
            tournament_type_id=tournament_type_id("classic_v3"),
        )
        async with session_factory() as session:
            before = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )
        assert [(item.date, item.registration_open) for item in before] == [
            (date(2026, 8, 12), True),
            (date(2026, 8, 13), False),
        ]

        approved = await service.approve_calendar_week(1, year=2026, month=8, row_number=3)

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
            1,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("bounty_v3"),
        )

        changed = await service.change_calendar_tournament_type(
            1,
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
                scoring_config_id=1,
                tournament_type_id=tournament_type_id("classic_v2"),
                date=date(2026, 8, 8),
                status=TournamentStatus.ACTIVE,
            )
            closed = Tournament(
                season_id=1,
                scoring_config_id=1,
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
            await service.delete_calendar_tournament(1, tournament_id=current_id)
        with pytest.raises(CalendarTournamentNotEditableError):
            await service.delete_calendar_tournament(1, tournament_id=closed_id)
    finally:
        await engine.dispose()


async def test_calendar_delete_removes_registrations_but_keeps_users(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_planning_service(tmp_path / "delete-reg.db")
    try:
        await seed_calendar_data(session_factory)
        tournament = await service.create_calendar_tournament(
            1,
            tournament_date=date(2026, 8, 12),
            tournament_type_id=tournament_type_id("classic_v3"),
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
            1,
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
            1,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
        )

        august = await service.create_calendar_tournament(
            1,
            tournament_date=date(2026, 8, 26),
            tournament_type_id=tournament_type_id("classic_v3"),
        )
        september = await service.create_calendar_tournament(
            1,
            tournament_date=date(2026, 9, 2),
            tournament_type_id=tournament_type_id("classic_v3"),
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
