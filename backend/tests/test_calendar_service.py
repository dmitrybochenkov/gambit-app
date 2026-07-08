import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import ScoringConfig, Season, Tournament
from app.db.models.enums import AdminPromptStatus, SeasonStatus, TournamentStatus
from app.services.calendar_service import (
    CalendarPromptAction,
    CalendarService,
)


async def create_calendar_service(
    database_path: Path,
) -> tuple[CalendarService, async_sessionmaker, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return CalendarService(session_factory), session_factory, engine


async def test_collects_weekly_tournament_prompt_on_sunday(tmp_path: Path) -> None:
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

        prompts = await service.collect_due_prompts(today=date(2026, 7, 12))
        await service.mark_prompt_notified(prompts[0].id)
        repeated_prompts = await service.collect_due_prompts(today=date(2026, 7, 12))

        assert len(prompts) == 1
        assert repeated_prompts == []
        prompt = prompts[0]
        assert prompt.kind == "tournaments_proposal"
        payload = json.loads(prompt.payload)
        assert [item["date"] for item in payload["tournaments"]] == [
            "2026-07-15",
            "2026-07-16",
            "2026-07-17",
            "2026-07-22",
            "2026-07-23",
            "2026-07-24",
        ]
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

        prompt = (await service.collect_due_prompts(today=date(2026, 7, 12)))[0]
        await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        async with session_factory() as session:
            tournaments = list((await session.execute(select(Tournament))).scalars())

        assert len(tournaments) == 6
        assert [(tournament.date, tournament.type) for tournament in tournaments] == [
            (date(2026, 7, 15), 1),
            (date(2026, 7, 16), 2),
            (date(2026, 7, 17), 3),
            (date(2026, 7, 22), 1),
            (date(2026, 7, 23), 2),
            (date(2026, 7, 24), 3),
        ]
        assert all(tournament.status == TournamentStatus.ACTIVE for tournament in tournaments)
    finally:
        await engine.dispose()


async def test_collects_season_prompt_seven_days_before_end(tmp_path: Path) -> None:
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

        prompt = (await service.collect_due_prompts(today=date(2026, 8, 24)))[0]
        payload = json.loads(prompt.payload)

        assert prompt.kind == "season_proposal"
        assert payload["name"] == "Осень 2026"
        assert payload["starts_at"] == "2026-09-01"
        assert payload["ends_at"] == "2026-11-30"
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

        prompt = (await service.collect_due_prompts(today=date(2026, 8, 24)))[0]
        resolved = await service.resolve_prompt(
            prompt_id=prompt.id,
            admin_telegram_id=100,
            action=CalendarPromptAction.CONFIRM,
        )

        async with session_factory() as session:
            seasons = list(
                (await session.execute(select(Season).order_by(Season.starts_at))).scalars()
            )

        assert resolved.status == AdminPromptStatus.CONFIRMED
        assert [season.name for season in seasons] == ["Лето 2026", "Осень 2026"]
        assert seasons[0].status == SeasonStatus.ACTIVE
        assert seasons[1].status == SeasonStatus.UPCOMING
    finally:
        await engine.dispose()
