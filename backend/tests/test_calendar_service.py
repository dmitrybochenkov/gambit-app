import json
from datetime import date
from pathlib import Path

from conftest import (
    seed_tournament_configs_async,
    seed_tournament_types_async,
    seed_weekly_templates_async,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import ScoringConfig, Season, Tournament
from app.db.models.enums import AdminPromptStatus, SeasonStatus, TournamentStatus
from app.services.calendar_service import (
    CalendarPromptAction,
    CalendarPromptInvalidPayloadError,
    CalendarService,
    seasonal_season_for,
)


async def create_calendar_service(
    database_path: Path,
) -> tuple[CalendarService, async_sessionmaker, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return CalendarService(session_factory), session_factory, engine


async def test_manual_tournament_prompt_collects_next_week(tmp_path: Path) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
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
                    ends_at=date(2026, 8, 31),
                    status=SeasonStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.get_or_create_manual_tournaments_prompt(
            today=date(2026, 7, 12)
        )

        assert prompt.kind == "tournaments_proposal"
        payload = json.loads(prompt.payload)
        assert [item["date"] for item in payload["tournaments"]] == [
            "2026-07-15",
            "2026-07-16",
            "2026-07-17",
            "2026-07-18",
            "2026-07-19",
        ]
        assert [item["tournament_type_name"] for item in payload["tournaments"]] == [
            "Баунти турнир",
            "Классика",
            "Фризаут",
            "Double Double",
            "Mystery Bounty",
        ]
        assert payload["tournaments"][0]["entry_fee"] == 600
        assert payload["tournaments"][0]["entry_stack"] == 20_000
        assert payload["tournaments"][0]["addon_fee"] == 800
        assert payload["tournaments"][0]["addon_stack"] == 125_000
        assert payload["tournaments"][0]["rebuys"][0] == {
            "fee": 600,
            "stack": 30_000,
        }
    finally:
        await engine.dispose()


async def test_confirming_tournament_prompt_creates_tournaments(tmp_path: Path) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
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
                    ends_at=date(2026, 8, 31),
                    status=SeasonStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.get_or_create_manual_tournaments_prompt(
            today=date(2026, 7, 12)
        )
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert len(tournaments) == 5
        assert [
            (tournament.date, tournament.tournament_type_id)
            for tournament in tournaments
        ] == [
            (date(2026, 7, 15), 1),
            (date(2026, 7, 16), 2),
            (date(2026, 7, 17), 3),
            (date(2026, 7, 18), 4),
            (date(2026, 7, 19), 5),
        ]
        assert all(tournament.status == TournamentStatus.ACTIVE for tournament in tournaments)
    finally:
        await engine.dispose()


async def test_confirming_season_prompt_creates_upcoming_season(tmp_path: Path) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
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
                    ends_at=date(2026, 8, 31),
                    status=SeasonStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.get_or_create_manual_season_prompt(
            today=date(2026, 7, 18)
        )
        resolved = await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        async with session_factory() as session:
            seasons = list(
                (await session.execute(select(Season).order_by(Season.starts_at))).scalars()
            )

        assert resolved.status == AdminPromptStatus.CONFIRMED.value
        assert [season.name for season in seasons] == ["Лето 2026", "Осень 2026"]
        assert seasons[0].status == SeasonStatus.ACTIVE
        assert seasons[1].status == SeasonStatus.UPCOMING
    finally:
        await engine.dispose()


async def test_manual_season_prompt_can_be_created_before_season_end(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
        async with session_factory() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            session.add(
                Season(
                    name="Лето 2026",
                    scoring_config_id=config.id,
                    starts_at=date(2026, 6, 1),
                    ends_at=date(2026, 8, 31),
                    status=SeasonStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.get_or_create_manual_season_prompt(
            today=date(2026, 7, 18)
        )
        payload = json.loads(prompt.payload)

        assert prompt.kind == "season_proposal"
        assert payload["name"] == "Осень 2026"
    finally:
        await engine.dispose()


async def test_manual_season_prompt_reopens_resolved_prompt(tmp_path: Path) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
        async with session_factory() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            session.add(
                Season(
                    name="Лето 2026",
                    scoring_config_id=config.id,
                    starts_at=date(2026, 6, 1),
                    ends_at=date(2026, 8, 31),
                    status=SeasonStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.get_or_create_manual_season_prompt(
            today=date(2026, 7, 18)
        )
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CANCEL,
        )
        reopened = await service.get_or_create_manual_season_prompt(
            today=date(2026, 7, 18)
        )

        assert reopened.id == prompt.id
        assert reopened.status == AdminPromptStatus.PENDING.value
    finally:
        await engine.dispose()


async def test_updates_manual_season_prompt(tmp_path: Path) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
        async with session_factory() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            session.add(
                Season(
                    name="Лето 2026",
                    scoring_config_id=config.id,
                    starts_at=date(2026, 6, 1),
                    ends_at=date(2026, 8, 31),
                    status=SeasonStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.get_or_create_manual_season_prompt(
            today=date(2026, 7, 18)
        )
        updated = await service.update_season_prompt(
            prompt_id=prompt.id,
            name="Осенний сезон 2026",
            starts_at=date(2026, 9, 2),
        )
        payload = json.loads(updated.payload)

        assert payload["name"] == "Осенний сезон 2026"
        assert payload["starts_at"] == "2026-09-02"
        assert payload["ends_at"] == "2026-11-30"
    finally:
        await engine.dispose()


async def test_rejects_invalid_manual_season_period(tmp_path: Path) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
        async with session_factory() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            session.add(
                Season(
                    name="Лето 2026",
                    scoring_config_id=config.id,
                    starts_at=date(2026, 6, 1),
                    ends_at=date(2026, 8, 31),
                    status=SeasonStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.get_or_create_manual_season_prompt(
            today=date(2026, 7, 18)
        )
        try:
            await service.update_season_prompt(
                prompt_id=prompt.id,
                starts_at=date(2026, 12, 1),
            )
        except CalendarPromptInvalidPayloadError:
            pass
        else:
            raise AssertionError("invalid period was accepted")
    finally:
        await engine.dispose()


def test_winter_season_name_uses_start_year_only() -> None:
    season = seasonal_season_for(date(2026, 12, 1))

    assert season["name"] == "Зима 2026"
    assert season["starts_at"] == date(2026, 12, 1)
    assert season["ends_at"] == date(2027, 2, 28)


async def test_manual_tournament_prompt_uses_next_monday(tmp_path: Path) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
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
                    ends_at=date(2026, 8, 31),
                    status=SeasonStatus.ACTIVE,
                )
            )
            await session.commit()

        prompt = await service.get_or_create_manual_tournaments_prompt(
            today=date(2026, 7, 16)
        )
        payload = json.loads(prompt.payload)

        assert [item["date"] for item in payload["tournaments"]][:2] == [
            "2026-07-22",
            "2026-07-23",
        ]
    finally:
        await engine.dispose()


async def test_sync_season_statuses_closes_finished_and_opens_current(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_calendar_service(
        tmp_path / "calendar.db"
    )
    try:
        async with session_factory() as session:
            config = ScoringConfig()
            session.add(config)
            await session.flush()
            session.add_all(
                [
                    Season(
                        name="Лето 2026",
                        scoring_config_id=config.id,
                        starts_at=date(2026, 6, 1),
                        ends_at=date(2026, 8, 31),
                        status=SeasonStatus.ACTIVE,
                    ),
                    Season(
                        name="Осень 2026",
                        scoring_config_id=config.id,
                        starts_at=date(2026, 9, 1),
                        ends_at=date(2026, 11, 30),
                        status=SeasonStatus.UPCOMING,
                    ),
                ]
            )
            await session.commit()

        await service.sync_season_statuses(today=date(2026, 9, 2))

        async with session_factory() as session:
            seasons = list(
                (await session.execute(select(Season).order_by(Season.starts_at))).scalars()
            )

        assert [season.status for season in seasons] == [
            SeasonStatus.CLOSED,
            SeasonStatus.ACTIVE,
        ]
    finally:
        await engine.dispose()
