import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import (
    seed_tournament_configs_async,
    seed_tournament_types_async,
    seed_weekly_templates_async,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.db.models import AdminPrompt, ScoringConfig, Season, Tournament, TournamentType
from app.db.models.enums import (
    AdminPromptStatus,
    TournamentStatus,
    TournamentTypeStatus,
)
from app.services.calendar_service import (
    AdminPromptKind,
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarPromptAction,
    CalendarPromptAlreadyResolvedError,
    CalendarPromptInvalidPayloadError,
    CalendarService,
    CalendarSundayTournamentDateError,
    CalendarSundayTournamentTypeNotFoundError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentDateNotInPromptError,
    CalendarWeeklyPendingConflictError,
    CalendarWeeklyPromptEmptyError,
    CalendarWeeklyPromptIntegrityError,
    next_complete_game_week,
    weekly_tournaments_prompt_key,
)


async def create_calendar_service(
    database_path: Path,
) -> tuple[CalendarService, async_sessionmaker, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return CalendarService(session_factory), session_factory, engine


async def seed_calendar_data(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        config = ScoringConfig()
        session.add(config)
        await session.flush()
        await seed_tournament_types_async(session)
        await seed_tournament_configs_async(session)
        await seed_weekly_templates_async(session)
        session.add(
            Season(
                name="Лето 2026",
                scoring_config_id=config.id,
                starts_at=date(2026, 6, 1),
                ends_at=None,
            )
        )
        await session.commit()


def test_next_complete_game_week_starts_from_nearest_future_wednesday() -> None:
    assert next_complete_game_week(date(2026, 7, 21)) == (
        date(2026, 7, 22),
        date(2026, 7, 23),
        date(2026, 7, 24),
        date(2026, 7, 25),
        date(2026, 7, 26),
    )
    assert next_complete_game_week(date(2026, 7, 22)) == (
        date(2026, 7, 29),
        date(2026, 7, 30),
        date(2026, 7, 31),
        date(2026, 8, 1),
        date(2026, 8, 2),
    )
    assert next_complete_game_week(date(2026, 7, 26)) == (
        date(2026, 7, 29),
        date(2026, 7, 30),
        date(2026, 7, 31),
        date(2026, 8, 1),
        date(2026, 8, 2),
    )


def test_next_complete_game_week_crosses_year_boundary() -> None:
    assert next_complete_game_week(date(2026, 12, 29)) == (
        date(2026, 12, 30),
        date(2026, 12, 31),
        date(2027, 1, 1),
        date(2027, 1, 2),
        date(2027, 1, 3),
    )


async def test_weekly_tournament_prompt_contains_five_minimal_items(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        stored_prompt = await service.get_prompt(prompt.id)

        assert prompt.kind == "tournaments_proposal"
        async with session_factory() as session:
            prompt_model = await session.get(AdminPrompt, prompt.id)
            assert prompt_model is not None
            assert prompt_model.key == "tournaments:2026-07-22:2026-07-26:1"
            assert prompt_model.scope_key == "tournaments:2026-07-22:2026-07-26"
        payload = json.loads(stored_prompt.payload)
        assert payload["tournaments"] == [
            {
                "date": "2026-07-22",
                "tournament_type_id": 1,
            },
            {
                "date": "2026-07-23",
                "tournament_type_id": 2,
            },
            {
                "date": "2026-07-24",
                "tournament_type_id": 3,
            },
            {
                "date": "2026-07-25",
                "tournament_type_id": 4,
            },
            {
                "date": "2026-07-26",
                "tournament_type_id": 5,
            },
        ]
        assert all(set(item) == {"date", "tournament_type_id"} for item in payload["tournaments"])
        assert [item.date for item in prompt.tournaments] == [
            date(2026, 7, 22),
            date(2026, 7, 23),
            date(2026, 7, 24),
            date(2026, 7, 25),
            date(2026, 7, 26),
        ]
        assert [item.date.weekday() for item in prompt.tournaments] == [2, 3, 4, 5, 6]
        assert prompt.tournaments[0].tournament_type.name == "Баунти турнир"
        assert prompt.tournaments[0].tournament_type.entry_fee == 600
        assert prompt.tournaments[0].tournament_type.entry_stack == 20_000
        assert prompt.tournaments[0].tournament_type.addon_fee == 800
        assert prompt.tournaments[0].tournament_type.addon_stack == 125_000
        assert prompt.tournaments[0].tournament_type.rebuys[0].fee == 600
        assert prompt.tournaments[0].tournament_type.rebuys[0].stack == 30_000

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert tournaments == []
    finally:
        await engine.dispose()


async def test_weekly_prompt_uses_deterministic_sunday_rotation(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 28))

        assert [item.date for item in prompt.tournaments] == [
            date(2026, 7, 29),
            date(2026, 7, 30),
            date(2026, 7, 31),
            date(2026, 8, 1),
            date(2026, 8, 2),
        ]
        assert [item.tournament_type.id for item in prompt.tournaments] == [1, 2, 3, 4, 6]
        assert prompt.tournaments[4].tournament_type.name == "Boss Bounty"
    finally:
        await engine.dispose()


async def test_weekly_prompt_uses_latest_actual_sunday_tournament_for_rotation(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=6,
                    date=date(2026, 7, 26),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 28))

        assert prompt.tournaments[4].date == date(2026, 8, 2)
        assert prompt.tournaments[4].tournament_type.id == 5
        assert prompt.tournaments[4].tournament_type.name == "Mystery Bounty"
    finally:
        await engine.dispose()


async def test_pending_prompts_do_not_advance_sunday_rotation(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 28))

        assert prompt.tournaments[4].date == date(2026, 8, 2)
        assert prompt.tournaments[4].tournament_type.id == 6
    finally:
        await engine.dispose()


async def test_confirmed_sunday_advances_sunday_rotation_default(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        assert prompt.tournaments[4].date == date(2026, 7, 26)
        assert prompt.tournaments[4].tournament_type.id == 5

        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        next_prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 28))

        assert next_prompt.tournaments[4].date == date(2026, 8, 2)
        assert next_prompt.tournaments[4].tournament_type.id == 6
    finally:
        await engine.dispose()


async def test_confirmed_manual_sunday_override_drives_next_rotation_default(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 28))
        await service.update_weekly_prompt_day_type(
            prompt_id=prompt.id,
            tournament_date=date(2026, 8, 2),
            tournament_type_id=5,
        )
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        next_prompt = await service.create_weekly_tournament_prompt(today=date(2026, 8, 4))

        assert next_prompt.tournaments[4].date == date(2026, 8, 9)
        assert next_prompt.tournaments[4].tournament_type.id == 6
    finally:
        await engine.dispose()


async def test_confirmed_prompt_without_tournaments_does_not_advance_sunday_rotation(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        target_dates = next_complete_game_week(date(2026, 7, 21))
        scope_key = weekly_tournaments_prompt_key(target_dates)
        async with session_factory() as session:
            session.add(
                AdminPrompt(
                    key=f"{scope_key}:1",
                    scope_key=scope_key,
                    kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                    payload=json.dumps(
                        {
                            "tournaments": [
                                {"date": "2026-07-26", "tournament_type_id": 5},
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    status=AdminPromptStatus.CONFIRMED,
                )
            )
            await session.commit()

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 28))

        assert prompt.tournaments[4].date == date(2026, 8, 2)
        assert prompt.tournaments[4].tournament_type.id == 6
    finally:
        await engine.dispose()


async def test_non_rotation_sunday_tournament_is_ignored_for_rotation_default(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=2,
                    date=date(2026, 7, 26),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 28))

        assert prompt.tournaments[4].date == date(2026, 8, 2)
        assert prompt.tournaments[4].tournament_type.id == 6
    finally:
        await engine.dispose()


async def test_confirming_weekly_tournament_prompt_creates_all_tournaments(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert [(t.date, t.tournament_type_id, t.status) for t in tournaments] == [
            (date(2026, 7, 22), 1, TournamentStatus.ACTIVE),
            (date(2026, 7, 23), 2, TournamentStatus.ACTIVE),
            (date(2026, 7, 24), 3, TournamentStatus.ACTIVE),
            (date(2026, 7, 25), 4, TournamentStatus.ACTIVE),
            (date(2026, 7, 26), 5, TournamentStatus.ACTIVE),
        ]
    finally:
        await engine.dispose()


async def test_confirming_weekly_prompt_rejects_missing_date_payload(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            stored_prompt = await session.get(AdminPrompt, prompt.id)
            assert stored_prompt is not None
            payload = json.loads(stored_prompt.payload)
            payload["tournaments"] = payload["tournaments"][:4]
            stored_prompt.payload = json.dumps(payload, ensure_ascii=False)
            await session.commit()

        with pytest.raises(CalendarPromptInvalidPayloadError):
            await service.resolve_prompt(
                prompt_id=prompt.id,
                admin_telegram_id=100,
                action=CalendarPromptAction.CONFIRM,
            )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert tournaments == []
    finally:
        await engine.dispose()


async def test_confirming_weekly_prompt_assigns_season_by_tournament_date(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            active = (await session.execute(select(Season))).scalar_one()
            active.ends_at = date(2026, 7, 23)
            config = await session.get(ScoringConfig, active.scoring_config_id)
            assert config is not None
            scheduled = Season(
                name="Осень 2026",
                scoring_config_id=config.id,
                starts_at=date(2026, 7, 24),
                ends_at=None,
            )
            session.add(scheduled)
            await session.commit()
            active_id = active.id
            scheduled_id = scheduled.id

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        async with session_factory() as session:
            tournaments = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )

        assert [(t.date, t.season_id) for t in tournaments] == [
            (date(2026, 7, 22), active_id),
            (date(2026, 7, 23), active_id),
            (date(2026, 7, 24), scheduled_id),
            (date(2026, 7, 25), scheduled_id),
            (date(2026, 7, 26), scheduled_id),
        ]
    finally:
        await engine.dispose()


async def test_weekly_prompt_type_update_changes_displayed_parameters(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        updated_prompt = await service.update_weekly_prompt_day_type(
            prompt_id=prompt.id,
            tournament_date=date(2026, 7, 24),
            tournament_type_id=4,
        )

        assert updated_prompt.tournaments[2].date == date(2026, 7, 24)
        assert updated_prompt.tournaments[2].tournament_type.name == "Double Double"
        assert updated_prompt.tournaments[2].tournament_type.entry_fee == 800
        assert updated_prompt.tournaments[2].tournament_type.entry_stack == 40_000
        assert updated_prompt.tournaments[2].tournament_type.rebuys[0].fee == 800

        payload = json.loads((await service.get_prompt(prompt.id)).payload)
        assert payload["tournaments"] == [
            {"date": "2026-07-22", "tournament_type_id": 1},
            {"date": "2026-07-23", "tournament_type_id": 2},
            {"date": "2026-07-24", "tournament_type_id": 4},
            {"date": "2026-07-25", "tournament_type_id": 4},
            {"date": "2026-07-26", "tournament_type_id": 5},
        ]
    finally:
        await engine.dispose()


async def test_weekly_prompt_thursday_and_saturday_can_be_edited_independently(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        thursday_prompt = await service.update_weekly_prompt_day_type(
            prompt_id=prompt.id,
            tournament_date=date(2026, 7, 23),
            tournament_type_id=5,
        )
        saturday_prompt = await service.update_weekly_prompt_day_type(
            prompt_id=prompt.id,
            tournament_date=date(2026, 7, 25),
            tournament_type_id=2,
        )

        assert [(item.date, item.tournament_type.id) for item in thursday_prompt.tournaments] == [
            (date(2026, 7, 22), 1),
            (date(2026, 7, 23), 5),
            (date(2026, 7, 24), 3),
            (date(2026, 7, 25), 4),
            (date(2026, 7, 26), 5),
        ]
        assert [(item.date, item.tournament_type.id) for item in saturday_prompt.tournaments] == [
            (date(2026, 7, 22), 1),
            (date(2026, 7, 23), 5),
            (date(2026, 7, 24), 3),
            (date(2026, 7, 25), 2),
            (date(2026, 7, 26), 5),
        ]
    finally:
        await engine.dispose()


async def test_weekly_prompt_day_edit_options_require_prompt_date(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            session.add(
                TournamentType(
                    id=99,
                    code="legacy_unknown",
                    name="Неопределенный турнир",
                    status=TournamentTypeStatus.ACTIVE,
                )
            )
            await session.commit()

        edit_view = await service.get_weekly_prompt_day_edit_options(
            prompt_id=prompt.id,
            tournament_date=date(2026, 7, 22),
        )

        assert edit_view.prompt_id == prompt.id
        assert edit_view.tournament_date == date(2026, 7, 22)
        assert [option.name for option in edit_view.tournament_types] == [
            "Баунти турнир",
            "Классика",
            "Фризаут",
            "Double Double",
            "Mystery Bounty",
            "Boss Bounty",
        ]
        assert "Неопределенный турнир" not in [option.name for option in edit_view.tournament_types]

        with pytest.raises(CalendarTournamentDateNotInPromptError):
            await service.get_weekly_prompt_day_edit_options(
                prompt_id=prompt.id,
                tournament_date=date(2026, 7, 27),
            )
    finally:
        await engine.dispose()


async def test_weekly_prompt_rejects_inactive_selected_type(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            double_double = await session.get(TournamentType, 4)
            assert double_double is not None
            double_double.status = TournamentTypeStatus.ARCHIVED
            await session.commit()

        with pytest.raises(CalendarPromptInvalidPayloadError):
            await service.update_weekly_prompt_day_type(
                prompt_id=prompt.id,
                tournament_date=date(2026, 7, 24),
                tournament_type_id=4,
            )
    finally:
        await engine.dispose()


async def test_creating_weekly_prompt_rejects_existing_tournament_on_any_target_date(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=2,
                    date=date(2026, 7, 24),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
    finally:
        await engine.dispose()


async def test_creating_weekly_prompt_reuses_pending_prompt_for_same_week(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        first_prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        second_prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        assert second_prompt.id == first_prompt.id
        assert second_prompt.tournaments == first_prompt.tournaments
    finally:
        await engine.dispose()


async def test_creating_weekly_prompt_preserves_manual_edits_to_pending_payload(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        updated_prompt = await service.update_weekly_prompt_day_type(
            prompt_id=prompt.id,
            tournament_date=date(2026, 7, 23),
            tournament_type_id=5,
        )
        reopened_prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        assert reopened_prompt.id == prompt.id
        assert reopened_prompt.tournaments == updated_prompt.tournaments
        assert reopened_prompt.tournaments[1].tournament_type.id == 5
    finally:
        await engine.dispose()


async def test_confirming_weekly_prompt_rejects_non_consecutive_payload(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            stored_prompt = await session.get(AdminPrompt, prompt.id)
            assert stored_prompt is not None
            stored_prompt.payload = json.dumps(
                {
                    "tournaments": [
                        {"date": "2026-07-22", "tournament_type_id": 1},
                        {"date": "2026-07-23", "tournament_type_id": 2},
                        {"date": "2026-07-24", "tournament_type_id": 3},
                        {"date": "2026-07-25", "tournament_type_id": 4},
                        {"date": "2026-07-27", "tournament_type_id": 5},
                    ]
                },
                ensure_ascii=False,
            )
            await session.commit()

        with pytest.raises(CalendarPromptInvalidPayloadError):
            await service.resolve_prompt(
                prompt_id=prompt.id,
                admin_telegram_id=100,
                action=CalendarPromptAction.CONFIRM,
            )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert tournaments == []
    finally:
        await engine.dispose()


async def test_cancelled_weekly_prompt_remains_historical_and_new_open_creates_new_row(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        target_dates = next_complete_game_week(date(2026, 7, 21))
        scope_key = weekly_tournaments_prompt_key(target_dates)
        async with session_factory() as session:
            stored = AdminPrompt(
                key=f"{scope_key}:1",
                scope_key=scope_key,
                kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                payload=json.dumps(
                    {
                        "tournaments": [
                            {"date": "2026-07-22", "tournament_type_id": 1},
                            {"date": "2026-07-23", "tournament_type_id": 2},
                            {"date": "2026-07-24", "tournament_type_id": 3},
                            {"date": "2026-07-25", "tournament_type_id": 4},
                            {"date": "2026-07-26", "tournament_type_id": 5},
                        ]
                    },
                    ensure_ascii=False,
                ),
                status=AdminPromptStatus.CANCELLED,
            )
            session.add(stored)
            await session.commit()
            cancelled_id = stored.id

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        assert prompt.id != cancelled_id
        async with session_factory() as session:
            prompts = list(
                (await session.execute(select(AdminPrompt).order_by(AdminPrompt.id))).scalars()
            )
        assert [
            (stored_prompt.key, stored_prompt.scope_key, stored_prompt.status)
            for stored_prompt in prompts
        ] == [
            (f"{scope_key}:1", scope_key, AdminPromptStatus.CANCELLED),
            (f"{scope_key}:2", scope_key, AdminPromptStatus.PENDING),
        ]
    finally:
        await engine.dispose()


async def test_weekly_prompt_attempt_key_uses_max_existing_numeric_suffix(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        target_dates = next_complete_game_week(date(2026, 7, 21))
        scope_key = weekly_tournaments_prompt_key(target_dates)
        payload = json.dumps(
            {
                "tournaments": [
                    {"date": "2026-07-22", "tournament_type_id": 1},
                    {"date": "2026-07-23", "tournament_type_id": 2},
                    {"date": "2026-07-24", "tournament_type_id": 3},
                    {"date": "2026-07-25", "tournament_type_id": 4},
                    {"date": "2026-07-26", "tournament_type_id": 5},
                ]
            },
            ensure_ascii=False,
        )
        async with session_factory() as session:
            session.add_all(
                [
                    AdminPrompt(
                        key=f"{scope_key}:1",
                        scope_key=scope_key,
                        kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                        payload=payload,
                        status=AdminPromptStatus.CANCELLED,
                    ),
                    AdminPrompt(
                        key=f"{scope_key}:3",
                        scope_key=scope_key,
                        kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                        payload=payload,
                        status=AdminPromptStatus.CANCELLED,
                    ),
                ]
            )
            await session.commit()

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        async with session_factory() as session:
            stored_prompt = await session.get(AdminPrompt, prompt.id)
            assert stored_prompt is not None
            assert stored_prompt.key == f"{scope_key}:4"
    finally:
        await engine.dispose()


async def test_confirmed_weekly_prompt_remains_terminal_when_tournaments_exist(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        async with session_factory() as session:
            stored_prompt = await session.get(AdminPrompt, prompt.id)
            assert stored_prompt is not None
            assert stored_prompt.status == AdminPromptStatus.CONFIRMED
    finally:
        await engine.dispose()


async def test_confirmed_weekly_prompt_with_wrong_type_is_integrity_error(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        target_dates = next_complete_game_week(date(2026, 7, 21))
        scope_key = weekly_tournaments_prompt_key(target_dates)
        async with session_factory() as session:
            session.add(
                AdminPrompt(
                    key=f"{scope_key}:1",
                    scope_key=scope_key,
                    kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                    payload=json.dumps(
                        {
                            "tournaments": [
                                {"date": "2026-07-22", "tournament_type_id": 1},
                                {"date": "2026-07-23", "tournament_type_id": 2},
                                {"date": "2026-07-24", "tournament_type_id": 3},
                                {"date": "2026-07-25", "tournament_type_id": 4},
                                {"date": "2026-07-26", "tournament_type_id": 5},
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    status=AdminPromptStatus.CONFIRMED,
                )
            )
            session.add_all(
                [
                    Tournament(
                        season_id=1,
                        tournament_type_id=1,
                        date=date(2026, 7, 22),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=2,
                        date=date(2026, 7, 24),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=2,
                        date=date(2026, 7, 23),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=4,
                        date=date(2026, 7, 25),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=5,
                        date=date(2026, 7, 26),
                        status=TournamentStatus.ACTIVE,
                    ),
                ]
            )
            await session.commit()

        with pytest.raises(CalendarWeeklyPromptIntegrityError):
            await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
    finally:
        await engine.dispose()


async def test_confirmed_weekly_prompt_without_tournaments_is_integrity_error(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        target_dates = next_complete_game_week(date(2026, 7, 21))
        scope_key = weekly_tournaments_prompt_key(target_dates)
        async with session_factory() as session:
            session.add(
                AdminPrompt(
                    key=f"{scope_key}:1",
                    scope_key=scope_key,
                    kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                    payload=json.dumps(
                        {
                            "tournaments": [
                                {"date": "2026-07-22", "tournament_type_id": 1},
                                {"date": "2026-07-23", "tournament_type_id": 2},
                                {"date": "2026-07-24", "tournament_type_id": 3},
                                {"date": "2026-07-25", "tournament_type_id": 4},
                                {"date": "2026-07-26", "tournament_type_id": 5},
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    status=AdminPromptStatus.CONFIRMED,
                )
            )
            await session.commit()

        with pytest.raises(CalendarWeeklyPromptIntegrityError):
            await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
    finally:
        await engine.dispose()


async def test_weekly_scope_allows_resolved_prompts_and_one_pending_prompt(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        first = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        await service.resolve_prompt(
            prompt_id=first.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CANCEL,
        )
        second = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        assert first.id != second.id
        assert second.status == AdminPromptStatus.PENDING.value
    finally:
        await engine.dispose()


async def test_weekly_scope_rejects_second_pending_prompt_at_database_level(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            stored_prompt = await session.get(AdminPrompt, prompt.id)
            assert stored_prompt is not None
            session.add(
                AdminPrompt(
                    key=f"{stored_prompt.scope_key}:manual-conflict",
                    scope_key=stored_prompt.scope_key,
                    kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                    payload=stored_prompt.payload,
                    status=AdminPromptStatus.PENDING,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()


async def test_weekly_prompt_creation_recovers_existing_pending_after_scope_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        calls = 0

        async def fake_commit(session: AsyncSession) -> None:
            nonlocal calls
            calls += 1
            created_prompt = next(item for item in session.new if isinstance(item, AdminPrompt))
            scope_key = created_prompt.scope_key
            assert scope_key is not None
            payload = created_prompt.payload
            await session.rollback()
            async with session_factory() as recovery_session:
                recovery_session.add(
                    AdminPrompt(
                        key=f"{scope_key}:2",
                        scope_key=scope_key,
                        kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                        payload=payload,
                        status=AdminPromptStatus.PENDING,
                    )
                )
                await recovery_session.commit()
            raise CalendarWeeklyPendingConflictError

        monkeypatch.setattr(
            CalendarService,
            "_commit_tournament_prompt",
            staticmethod(fake_commit),
        )

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        assert calls == 1
        async with session_factory() as session:
            stored_prompts = list((await session.execute(select(AdminPrompt))).scalars())
        assert len(stored_prompts) == 1
        assert stored_prompts[0].key == "tournaments:2026-07-22:2026-07-26:2"
        assert prompt.id == stored_prompts[0].id
        assert len(prompt.tournaments) == 5
    finally:
        await engine.dispose()


async def test_confirming_weekly_prompt_rejects_duplicate_tournament_date(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=2,
                    date=date(2026, 7, 24),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.resolve_prompt(
                prompt_id=prompt.id,
                admin_telegram_id=100,
                action=CalendarPromptAction.CONFIRM,
            )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert len(tournaments) == 1
        assert tournaments[0].date == date(2026, 7, 24)
    finally:
        await engine.dispose()


async def test_confirming_weekly_prompt_rejects_conflict_on_any_target_date(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=2,
                    date=date(2026, 7, 24),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.resolve_prompt(
                prompt_id=prompt.id,
                admin_telegram_id=100,
                action=CalendarPromptAction.CONFIRM,
            )

        async with session_factory() as session:
            tournaments = list(
                (await session.execute(select(Tournament).order_by(Tournament.date))).scalars()
            )

        assert [(t.date, t.tournament_type_id) for t in tournaments] == [(date(2026, 7, 24), 2)]
    finally:
        await engine.dispose()


async def test_repeated_weekly_prompt_confirmation_does_not_create_second_schedule(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )
        with pytest.raises(CalendarPromptAlreadyResolvedError):
            await service.resolve_prompt(
                prompt_id=prompt.id,
                admin_telegram_id=100,
                action=CalendarPromptAction.CONFIRM,
            )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert len(tournaments) == 5
    finally:
        await engine.dispose()


async def test_created_weekly_schedule_uses_materialized_tournaments(
    tmp_path: Path,
) -> None:
    service, _session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(service.session_factory)
        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        schedule = await service.get_created_weekly_schedule(prompt.id)

        assert [(item.date, item.tournament_type_name) for item in schedule.tournaments] == [
            (date(2026, 7, 22), "Баунти турнир"),
            (date(2026, 7, 23), "Классика"),
            (date(2026, 7, 24), "Фризаут"),
            (date(2026, 7, 25), "Double Double"),
            (date(2026, 7, 26), "Mystery Bounty"),
        ]
        assert schedule.tournaments[0].entry_fee == 600
        assert schedule.tournaments[0].entry_stack == 20_000
        assert [rebuy.fee for rebuy in schedule.tournaments[0].rebuys] == [
            600,
            800,
            800,
            800,
            1000,
            1000,
        ]
        assert schedule.tournaments[4].tournament_type_code == "mystery_bounty"
    finally:
        await engine.dispose()


async def test_created_weekly_schedule_rejects_unconfirmed_prompt(
    tmp_path: Path,
) -> None:
    service, _session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(service.session_factory)
        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        with pytest.raises(CalendarPromptAlreadyResolvedError):
            await service.get_created_weekly_schedule(prompt.id)
    finally:
        await engine.dispose()


async def test_weekly_prompt_requires_configured_default_types(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            freezeout = await session.get(TournamentType, 3)
            assert freezeout is not None
            freezeout.status = TournamentTypeStatus.ARCHIVED
            await session.commit()

        with pytest.raises(CalendarDefaultTournamentTypeNotFoundError):
            await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
    finally:
        await engine.dispose()


async def test_confirming_weekly_prompt_rejects_non_weekly_payload(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            stored_prompt = await session.get(AdminPrompt, prompt.id)
            assert stored_prompt is not None
            stored_prompt.payload = json.dumps(
                {
                    "tournaments": [
                        {"date": "2026-07-22", "tournament_type_id": 1},
                        {"date": "2026-07-28", "tournament_type_id": 2},
                    ]
                },
                ensure_ascii=False,
            )
            await session.commit()

        with pytest.raises(CalendarPromptInvalidPayloadError):
            await service.resolve_prompt(
                prompt_id=prompt.id,
                admin_telegram_id=100,
                action=CalendarPromptAction.CONFIRM,
            )
    finally:
        await engine.dispose()


async def test_confirming_weekly_prompt_rejects_empty_payload(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            stored_prompt = await session.get(AdminPrompt, prompt.id)
            assert stored_prompt is not None
            stored_prompt.payload = json.dumps({"tournaments": []}, ensure_ascii=False)
            await session.commit()

        with pytest.raises(CalendarWeeklyPromptEmptyError):
            await service.resolve_prompt(
                prompt_id=prompt.id,
                admin_telegram_id=100,
                action=CalendarPromptAction.CONFIRM,
            )
    finally:
        await engine.dispose()


async def test_confirming_weekly_prompt_rolls_back_when_selected_type_is_unavailable(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        async with session_factory() as session:
            bounty = await session.get(TournamentType, 1)
            assert bounty is not None
            bounty.status = TournamentTypeStatus.ARCHIVED
            await session.commit()

        with pytest.raises(CalendarPromptInvalidPayloadError):
            await service.resolve_prompt(
                prompt_id=prompt.id,
                admin_telegram_id=100,
                action=CalendarPromptAction.CONFIRM,
            )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert tournaments == []
    finally:
        await engine.dispose()


async def test_commit_maps_tournament_date_unique_integrity_error() -> None:
    session = AsyncMock()
    session.commit.side_effect = IntegrityError(
        "INSERT INTO tournaments",
        {},
        Exception("UNIQUE constraint failed: tournaments.date"),
    )

    with pytest.raises(CalendarTournamentDateAlreadyExistsError):
        await CalendarService._commit_tournament_prompt(session)

    session.rollback.assert_awaited_once()


async def test_commit_maps_pending_scope_unique_integrity_error() -> None:
    session = AsyncMock()
    session.commit.side_effect = IntegrityError(
        "INSERT INTO admin_prompts",
        {},
        Exception("UNIQUE constraint failed: admin_prompts.kind, admin_prompts.scope_key"),
    )

    with pytest.raises(CalendarWeeklyPendingConflictError):
        await CalendarService._commit_tournament_prompt(session)

    session.rollback.assert_awaited_once()


async def test_weekly_prompt_date_update_is_not_supported(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

        with pytest.raises(CalendarTournamentDateNotInPromptError):
            await service.update_weekly_prompt_day_type(
                prompt_id=prompt.id,
                tournament_date=date(2026, 7, 27),
                tournament_type_id=1,
            )
    finally:
        await engine.dispose()


async def test_recommended_sunday_tournament_type_resolves_active_type(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        tournament_type = await service.get_recommended_sunday_tournament_type(date(2026, 7, 26))

        assert tournament_type.id == 5
        assert tournament_type.name == "Mystery Bounty"
    finally:
        await engine.dispose()


async def test_recommended_sunday_tournament_type_rejects_non_sunday(
    tmp_path: Path,
) -> None:
    service, _session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        with pytest.raises(CalendarSundayTournamentDateError):
            await service.get_recommended_sunday_tournament_type(date(2026, 7, 27))
    finally:
        await engine.dispose()


async def test_recommended_sunday_tournament_type_requires_configured_type(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        async with session_factory() as session:
            await seed_tournament_types_async(session)
            boss = await session.get(TournamentType, 6)
            assert boss is not None
            await session.delete(boss)
            await session.commit()

        with pytest.raises(CalendarSundayTournamentTypeNotFoundError):
            await service.get_recommended_sunday_tournament_type(date(2026, 8, 2))
    finally:
        await engine.dispose()


async def test_recommended_sunday_tournament_type_requires_active_type(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        async with session_factory() as session:
            await seed_tournament_types_async(session)
            boss = await session.get(TournamentType, 6)
            assert boss is not None
            boss.status = TournamentTypeStatus.ARCHIVED
            await session.commit()

        with pytest.raises(CalendarSundayTournamentTypeNotFoundError):
            await service.get_recommended_sunday_tournament_type(date(2026, 8, 2))
    finally:
        await engine.dispose()


async def test_latest_previous_sunday_tournament_drives_sunday_recommendation(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    Tournament(
                        season_id=1,
                        tournament_type_id=5,
                        date=date(2026, 7, 19),
                        status=TournamentStatus.ACTIVE,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=5,
                        date=date(2026, 8, 9),
                        status=TournamentStatus.ACTIVE,
                    ),
                ]
            )
            await session.commit()

        first_recommendation = await service.get_recommended_sunday_tournament_type(
            date(2026, 8, 2)
        )

        async with session_factory() as session:
            historical = (
                await session.execute(
                    select(Tournament).where(Tournament.date == date(2026, 7, 19))
                )
            ).scalar_one()
            await session.delete(historical)
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=6,
                    date=date(2026, 7, 12),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        second_recommendation = await service.get_recommended_sunday_tournament_type(
            date(2026, 8, 2)
        )

        assert first_recommendation.id == 6
        assert first_recommendation.name == "Boss Bounty"
        assert second_recommendation.id == 5
        assert second_recommendation.name == "Mystery Bounty"
    finally:
        await engine.dispose()


async def test_closed_sunday_tournament_drives_rotation_but_cancelled_is_ignored(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    Tournament(
                        season_id=1,
                        tournament_type_id=5,
                        date=date(2026, 7, 19),
                        tournament_fund=1000,
                        status=TournamentStatus.CLOSED,
                    ),
                    Tournament(
                        season_id=1,
                        tournament_type_id=6,
                        date=date(2026, 7, 26),
                        status=TournamentStatus.CANCELLED,
                    ),
                ]
            )
            await session.commit()

        recommendation = await service.get_recommended_sunday_tournament_type(date(2026, 8, 2))

        assert recommendation.id == 6
        assert recommendation.name == "Boss Bounty"
    finally:
        await engine.dispose()
