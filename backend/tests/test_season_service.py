from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.common.clock import FixedClock
from app.db.base import Base
from app.db.factories import create_user
from app.db.models import ScoringConfig, Season
from app.db.models.enums import UserRole, UserStatus
from app.db.repositories.season_repository import SeasonRepository
from app.services.dto.seasons import SeasonLifecycleStateView
from app.services.season_service import (
    SeasonNameAlreadyExistsError,
    SeasonNameInvalidError,
    SeasonScheduledConflictError,
    SeasonScoringConfigNotFoundError,
    SeasonService,
    SeasonStartDateError,
    season_lifecycle_state,
    season_name_for_date,
)


async def create_season_service(
    database_path: Path,
    *,
    today: date = date(2026, 8, 9),
) -> tuple[SeasonService, async_sessionmaker, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return (
        SeasonService(
            session_factory,
            clock=FixedClock(datetime.combine(today, datetime.min.time())),
        ),
        session_factory,
        engine,
    )


async def seed_admin_and_config(async_session_factory: async_sessionmaker) -> int:
    async with async_session_factory() as session:
        admin = create_user(
            telegram_id=100,
            display_name="Админ",
            status=UserStatus.ACTIVE,
            role=UserRole.SUPERADMIN,
        )
        config = ScoringConfig()
        session.add_all([admin, config])
        await session.commit()
        return config.id


async def seed_current_season(
    async_session_factory: async_sessionmaker,
    *,
    name: str = "Лето 2026",
    starts_at: date = date(2026, 6, 1),
    ends_at: date | None = None,
) -> int:
    config_id = await seed_admin_and_config(async_session_factory)
    async with async_session_factory() as session:
        session.add(
            Season(
                name=name,
                scoring_config_id=config_id,
                starts_at=starts_at,
                ends_at=ends_at,
            )
        )
        await session.commit()
    return config_id


async def test_open_first_season(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)

        season = await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )

        assert season.name == "Осень 2026"
        assert season.starts_at == date(2026, 9, 1)
        assert season.ends_at is None
        assert season.lifecycle_state == SeasonLifecycleStateView.CURRENT
        assert season.scoring_config_id == config_id
    finally:
        await engine.dispose()


def test_season_name_for_date_uses_quarter_names() -> None:
    assert season_name_for_date(date(2026, 1, 15)) == "Зима 2026"
    assert season_name_for_date(date(2026, 3, 31)) == "Зима 2026"
    assert season_name_for_date(date(2026, 4, 1)) == "Весна 2026"
    assert season_name_for_date(date(2026, 6, 30)) == "Весна 2026"
    assert season_name_for_date(date(2026, 7, 1)) == "Лето 2026"
    assert season_name_for_date(date(2026, 9, 30)) == "Лето 2026"
    assert season_name_for_date(date(2026, 10, 1)) == "Осень 2026"
    assert season_name_for_date(date(2026, 12, 31)) == "Осень 2026"
    assert season_name_for_date(date(2027, 1, 1)) == "Зима 2027"


def test_season_lifecycle_state_is_derived_from_supplied_date() -> None:
    assert (
        season_lifecycle_state(
            starts_at=date(2026, 8, 1),
            ends_at=None,
            today=date(2026, 7, 31),
        )
        == SeasonLifecycleStateView.SCHEDULED
    )
    assert (
        season_lifecycle_state(
            starts_at=date(2026, 8, 1),
            ends_at=None,
            today=date(2026, 8, 1),
        )
        == SeasonLifecycleStateView.CURRENT
    )
    assert (
        season_lifecycle_state(
            starts_at=date(2026, 6, 1),
            ends_at=date(2026, 7, 31),
            today=date(2026, 8, 1),
        )
        == SeasonLifecycleStateView.COMPLETED
    )


async def test_get_season_timeline_has_no_pending_proposal(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "timeline.db")
    try:
        await seed_current_season(session_factory)

        timeline = await service.get_season_timeline(100)

        assert timeline.current_season is not None
        assert timeline.current_season.name == "Лето 2026"
        assert timeline.future_season is None
        assert timeline.suggested_start == date(2026, 8, 10)
        assert not hasattr(timeline, "pending_proposal")
    finally:
        await engine.dispose()


async def test_creation_preview_does_not_write_database(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "preview.db")
    try:
        await seed_current_season(session_factory)

        preview = await service.get_creation_preview(
            100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
        )

        assert preview.name == "Осень 2026"
        assert preview.starts_at == date(2026, 9, 1)
        assert preview.active_season_ends_at == date(2026, 8, 31)
        async with session_factory() as session:
            seasons = list((await session.execute(select(Season))).scalars())
        assert [season.name for season in seasons] == ["Лето 2026"]
    finally:
        await engine.dispose()


async def test_create_next_season_closes_current_atomically(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "create.db")
    try:
        await seed_current_season(session_factory)

        season = await service.create_next_season(
            100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
        )

        assert season.name == "Осень 2026"
        async with session_factory() as session:
            seasons = list(
                (await session.execute(select(Season).order_by(Season.starts_at))).scalars()
            )
        assert [(item.name, item.ends_at) for item in seasons] == [
            ("Лето 2026", date(2026, 8, 31)),
            ("Осень 2026", None),
        ]
    finally:
        await engine.dispose()


async def test_create_next_season_rejects_second_future_season(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "future.db")
    try:
        config_id = await seed_current_season(session_factory, ends_at=date(2026, 8, 31))
        async with session_factory() as session:
            session.add(
                Season(
                    name="Осень 2026",
                    scoring_config_id=config_id,
                    starts_at=date(2026, 9, 1),
                    ends_at=None,
                )
            )
            await session.commit()

        with pytest.raises(SeasonScheduledConflictError):
            await service.create_next_season(
                100,
                name="Зима 2026",
                starts_at=date(2026, 12, 1),
            )
    finally:
        await engine.dispose()


async def test_create_next_season_rejects_duplicate_name(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "duplicate.db")
    try:
        await seed_current_season(session_factory)

        with pytest.raises(SeasonNameAlreadyExistsError):
            await service.create_next_season(
                100,
                name="Лето 2026",
                starts_at=date(2026, 9, 1),
            )
    finally:
        await engine.dispose()


async def test_create_next_season_rejects_past_or_today(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "date.db")
    try:
        await seed_current_season(session_factory)

        with pytest.raises(SeasonStartDateError):
            await service.create_next_season(
                100,
                name="Сегодня",
                starts_at=date(2026, 8, 9),
            )
    finally:
        await engine.dispose()


async def test_delete_future_season_reopens_previous(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "delete.db")
    try:
        config_id = await seed_current_season(
            session_factory,
            ends_at=date(2026, 8, 31),
        )
        async with session_factory() as session:
            session.add(
                Season(
                    id=2,
                    name="Осень 2026",
                    scoring_config_id=config_id,
                    starts_at=date(2026, 9, 1),
                    ends_at=None,
                )
            )
            await session.commit()

        timeline = await service.delete_future_season(100, 2)

        assert timeline.future_season is None
        async with session_factory() as session:
            current = await SeasonRepository(session).get_by_name("Лето 2026")
            assert current is not None
            assert current.ends_at is None
            assert await SeasonRepository(session).get_by_name("Осень 2026") is None
    finally:
        await engine.dispose()


async def test_invalid_name_is_rejected(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "invalid.db")
    try:
        await seed_current_season(session_factory)

        with pytest.raises(SeasonNameInvalidError):
            await service.get_creation_preview(
                100,
                name="   ",
                starts_at=date(2026, 9, 1),
            )
    finally:
        await engine.dispose()


async def test_missing_scoring_config_is_rejected(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "config.db")
    try:
        async with session_factory() as session:
            session.add(
                create_user(
                    telegram_id=100,
                    display_name="Админ",
                    status=UserStatus.ACTIVE,
                    role=UserRole.SUPERADMIN,
                )
            )
            session.add(
                Season(
                    name="Лето 2026",
                    scoring_config_id=999,
                    starts_at=date(2026, 6, 1),
                    ends_at=None,
                )
            )
            await session.commit()

        with pytest.raises(SeasonScoringConfigNotFoundError):
            await service.get_creation_preview(
                100,
                name="Осень 2026",
                starts_at=date(2026, 9, 1),
            )
    finally:
        await engine.dispose()


async def test_create_next_season_rolls_back_on_error(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "rollback.db")
    try:
        await seed_current_season(session_factory)

        with pytest.raises(SeasonNameInvalidError):
            await service.create_next_season(
                100,
                name="",
                starts_at=date(2026, 9, 1),
            )

        async with session_factory() as session:
            current = await SeasonRepository(session).get_by_name("Лето 2026")
            assert current is not None
            assert current.ends_at is None
            seasons = list((await session.execute(select(Season))).scalars())
            assert len(seasons) == 1
    finally:
        await engine.dispose()


async def test_open_season_rejects_same_start(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "overlap.db")
    try:
        config_id = await seed_current_season(session_factory)

        with pytest.raises(SeasonStartDateError):
            await service.open_season(
                admin_telegram_id=100,
                name="Накладка",
                starts_at=date(2026, 6, 1),
                scoring_config_id=config_id,
            )
    finally:
        await engine.dispose()
