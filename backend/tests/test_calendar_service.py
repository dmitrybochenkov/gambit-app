import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import seed_tournament_configs_async, seed_tournament_types_async
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import AdminPrompt, ScoringConfig, Season, Tournament, TournamentType
from app.db.models.enums import (
    AdminPromptStatus,
    SeasonStatus,
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
    CalendarWeeklyPromptConflictError,
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
        session.add(
            Season(
                name="Лето 2026",
                scoring_config_id=config.id,
                starts_at=date(2026, 6, 1),
                ends_at=None,
                status=SeasonStatus.ACTIVE,
            )
        )
        await session.commit()


def test_next_complete_game_week_starts_from_nearest_future_wednesday() -> None:
    assert next_complete_game_week(date(2026, 7, 21)) == (
        date(2026, 7, 22),
        date(2026, 7, 24),
        date(2026, 7, 26),
    )
    assert next_complete_game_week(date(2026, 7, 22)) == (
        date(2026, 7, 29),
        date(2026, 7, 31),
        date(2026, 8, 2),
    )
    assert next_complete_game_week(date(2026, 7, 26)) == (
        date(2026, 7, 29),
        date(2026, 7, 31),
        date(2026, 8, 2),
    )


async def test_weekly_tournament_prompt_contains_three_minimal_items(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
        stored_prompt = await service.get_prompt(prompt.id)

        assert prompt.kind == "tournaments_proposal"
        payload = json.loads(stored_prompt.payload)
        assert payload["tournaments"] == [
            {
                "date": "2026-07-22",
                "tournament_type_id": 1,
            },
            {
                "date": "2026-07-24",
                "tournament_type_id": 3,
            },
            {
                "date": "2026-07-26",
                "tournament_type_id": 5,
            }
        ]
        assert all(set(item) == {"date", "tournament_type_id"} for item in payload["tournaments"])
        assert [item.date for item in prompt.tournaments] == [
            date(2026, 7, 22),
            date(2026, 7, 24),
            date(2026, 7, 26),
        ]
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
            date(2026, 7, 31),
            date(2026, 8, 2),
        ]
        assert [item.tournament_type.id for item in prompt.tournaments] == [1, 3, 6]
        assert prompt.tournaments[2].tournament_type.name == "Boss Bounty"
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
            (date(2026, 7, 24), 3, TournamentStatus.ACTIVE),
            (date(2026, 7, 26), 5, TournamentStatus.ACTIVE),
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

        assert updated_prompt.tournaments[1].date == date(2026, 7, 24)
        assert updated_prompt.tournaments[1].tournament_type.name == "Double Double"
        assert updated_prompt.tournaments[1].tournament_type.entry_fee == 800
        assert updated_prompt.tournaments[1].tournament_type.entry_stack == 40_000
        assert updated_prompt.tournaments[1].tournament_type.rebuys[0].fee == 800

        payload = json.loads((await service.get_prompt(prompt.id)).payload)
        assert payload["tournaments"] == [
            {"date": "2026-07-22", "tournament_type_id": 1},
            {"date": "2026-07-24", "tournament_type_id": 4},
            {"date": "2026-07-26", "tournament_type_id": 5},
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

        with pytest.raises(CalendarTournamentDateNotInPromptError):
            await service.get_weekly_prompt_day_edit_options(
                prompt_id=prompt.id,
                tournament_date=date(2026, 7, 23),
            )
    finally:
        await engine.dispose()


async def test_weekly_prompt_rejects_inactive_selected_type(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)
        async with session_factory() as session:
            double_double = await session.get(TournamentType, 4)
            assert double_double is not None
            double_double.status = TournamentTypeStatus.ARCHIVED
            await session.commit()

        prompt = await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))

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


async def test_creating_weekly_prompt_rejects_resolved_prompt_for_same_week(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        target_dates = next_complete_game_week(date(2026, 7, 21))
        async with session_factory() as session:
            session.add(
                AdminPrompt(
                    key=weekly_tournaments_prompt_key(target_dates),
                    kind=AdminPromptKind.TOURNAMENTS_PROPOSAL,
                    payload=json.dumps(
                        {
                            "tournaments": [
                                {"date": "2026-07-22", "tournament_type_id": 1},
                                {"date": "2026-07-24", "tournament_type_id": 3},
                                {"date": "2026-07-26", "tournament_type_id": 5},
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    status=AdminPromptStatus.CANCELLED,
                )
            )
            await session.commit()

        with pytest.raises(CalendarWeeklyPromptConflictError):
            await service.create_weekly_tournament_prompt(today=date(2026, 7, 21))
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

        assert len(tournaments) == 3
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
                tournament_date=date(2026, 7, 23),
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

        tournament_type = await service.get_recommended_sunday_tournament_type(
            date(2026, 7, 26)
        )

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


async def test_existing_tournaments_do_not_affect_sunday_recommendation(
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
                    date=date(2026, 8, 16),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        second_recommendation = await service.get_recommended_sunday_tournament_type(
            date(2026, 8, 2)
        )

        assert first_recommendation.id == 6
        assert first_recommendation.name == "Boss Bounty"
        assert second_recommendation == first_recommendation
    finally:
        await engine.dispose()
