import json
from datetime import date
from pathlib import Path

import pytest
from conftest import seed_tournament_configs_async, seed_tournament_types_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import AdminPrompt, ScoringConfig, Season, Tournament, TournamentType
from app.db.models.enums import SeasonStatus, TournamentStatus, TournamentTypeStatus
from app.services.calendar_service import (
    CalendarPromptAction,
    CalendarPromptAlreadyResolvedError,
    CalendarService,
    CalendarSundayTournamentDateError,
    CalendarSundayTournamentTypeNotFoundError,
    CalendarTournamentDateAlreadyExistsError,
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


async def test_manual_tournament_prompt_contains_only_date_and_type_id(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_manual_tournament_prompt(
            tournament_date=date(2026, 7, 22),
            tournament_type_id=1,
        )
        stored_prompt = await service.get_prompt(prompt.id)

        assert prompt.kind == "tournaments_proposal"
        payload = json.loads(stored_prompt.payload)
        assert payload["tournaments"] == [
            {
                "date": "2026-07-22",
                "tournament_type_id": 1,
            }
        ]
        assert set(payload["tournaments"][0]) == {
            "date",
            "tournament_type_id",
        }
        assert prompt.tournaments[0].tournament_type.name == "Баунти турнир"
        assert prompt.tournaments[0].tournament_type.entry_fee == 600
        assert prompt.tournaments[0].tournament_type.entry_stack == 20_000
        assert prompt.tournaments[0].tournament_type.addon_fee == 800
        assert prompt.tournaments[0].tournament_type.addon_stack == 125_000
        assert prompt.tournaments[0].tournament_type.rebuys[0].fee == 600
        assert prompt.tournaments[0].tournament_type.rebuys[0].stack == 30_000
    finally:
        await engine.dispose()


async def test_confirming_tournament_prompt_creates_selected_tournament(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_manual_tournament_prompt(
            tournament_date=date(2026, 7, 22),
            tournament_type_id=2,
        )
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert len(tournaments) == 1
        assert tournaments[0].date == date(2026, 7, 22)
        assert tournaments[0].tournament_type_id == 2
        assert tournaments[0].status == TournamentStatus.ACTIVE
    finally:
        await engine.dispose()


async def test_tournament_prompt_type_update_changes_displayed_parameters(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_manual_tournament_prompt(
            tournament_date=date(2026, 7, 22),
            tournament_type_id=1,
        )
        updated_prompt = await service.update_tournament_prompt_type(
            prompt_id=prompt.id,
            tournament_index=0,
            tournament_type_id=4,
        )

        assert updated_prompt.tournaments[0].date == date(2026, 7, 22)
        assert updated_prompt.tournaments[0].tournament_type.name == "Double Double"
        assert updated_prompt.tournaments[0].tournament_type.entry_fee == 800
        assert updated_prompt.tournaments[0].tournament_type.entry_stack == 40_000
        assert updated_prompt.tournaments[0].tournament_type.rebuys[0].fee == 800
    finally:
        await engine.dispose()


async def test_tournament_prompt_date_update_changes_date(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_manual_tournament_prompt(
            tournament_date=date(2026, 7, 22),
            tournament_type_id=1,
        )
        updated_prompt = await service.update_tournament_prompt_date(
            prompt_id=prompt.id,
            tournament_date=date(2026, 7, 23),
        )

        assert updated_prompt.tournaments[0].date == date(2026, 7, 23)
        assert updated_prompt.tournaments[0].tournament_type.id == 1
    finally:
        await engine.dispose()


async def test_creating_prompt_rejects_duplicate_tournament_date(
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
                    date=date(2026, 7, 22),
                    status=TournamentStatus.ACTIVE,
                )
            )
            await session.commit()

        with pytest.raises(CalendarTournamentDateAlreadyExistsError):
            await service.create_manual_tournament_prompt(
                tournament_date=date(2026, 7, 22),
                tournament_type_id=1,
            )
    finally:
        await engine.dispose()


async def test_confirming_prompt_rejects_duplicate_tournament_date(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_manual_tournament_prompt(
            tournament_date=date(2026, 7, 22),
            tournament_type_id=1,
        )
        async with session_factory() as session:
            session.add(
                Tournament(
                    season_id=1,
                    tournament_type_id=2,
                    date=date(2026, 7, 22),
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
    finally:
        await engine.dispose()


async def test_confirming_prompt_maps_unique_date_integrity_error(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_manual_tournament_prompt(
            tournament_date=date(2026, 7, 22),
            tournament_type_id=1,
        )
        async with session_factory() as session:
            stored_prompt = await session.get(AdminPrompt, prompt.id)
            assert stored_prompt is not None
            stored_prompt.payload = json.dumps(
                {
                    "tournaments": [
                        {
                            "date": "2026-07-22",
                            "tournament_type_id": 1,
                        },
                        {
                            "date": "2026-07-22",
                            "tournament_type_id": 2,
                        },
                    ]
                },
                ensure_ascii=False,
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

        assert tournaments == []
    finally:
        await engine.dispose()


async def test_repeated_prompt_confirmation_does_not_create_second_tournament(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(tmp_path / "calendar.db")
    try:
        await seed_calendar_data(session_factory)

        prompt = await service.create_manual_tournament_prompt(
            tournament_date=date(2026, 7, 22),
            tournament_type_id=1,
        )
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

        assert len(tournaments) == 1
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
