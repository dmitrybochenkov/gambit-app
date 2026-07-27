from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.factories import create_user
from app.db.models import ScoringConfig, Season, Tournament
from app.db.models.enums import SeasonStatus, TournamentStatus, UserRole, UserStatus
from app.db.repositories.season_repository import SeasonRepository
from app.services.dto import SeasonStatusView
from app.services.season_service import (
    SeasonConflictError,
    SeasonNameAlreadyExistsError,
    SeasonScoringConfigNotFoundError,
    SeasonService,
    SeasonStartDateError,
)


async def create_season_service(
    database_path: Path,
) -> tuple[SeasonService, async_sessionmaker, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return SeasonService(session_factory), session_factory, engine


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
        assert season.status == SeasonStatusView.ACTIVE
        assert season.scoring_config_id == config_id
    finally:
        await engine.dispose()


async def test_open_second_season_closes_previous(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        first = await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )

        second = await service.open_season(
            admin_telegram_id=100,
            name="Зима 2026",
            starts_at=date(2026, 12, 1),
            scoring_config_id=config_id,
        )

        async with session_factory() as session:
            seasons = list(
                (await session.execute(select(Season).order_by(Season.starts_at))).scalars()
            )

        assert second.status == SeasonStatusView.ACTIVE
        assert second.ends_at is None
        assert [(season.id, season.status, season.ends_at) for season in seasons] == [
            (first.id, SeasonStatus.CLOSED, date(2026, 11, 30)),
            (second.id, SeasonStatus.ACTIVE, None),
        ]
    finally:
        await engine.dispose()


async def test_cannot_open_season_before_current(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )

        with pytest.raises(SeasonStartDateError):
            await service.open_season(
                admin_telegram_id=100,
                name="Лето 2026",
                starts_at=date(2026, 6, 1),
                scoring_config_id=config_id,
            )

        active = await service.get_active_season()
        assert active.name == "Осень 2026"
        assert active.ends_at is None
    finally:
        await engine.dispose()


async def test_cannot_open_season_with_duplicate_name(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )

        with pytest.raises(SeasonNameAlreadyExistsError):
            await service.open_season(
                admin_telegram_id=100,
                name="Осень 2026",
                starts_at=date(2026, 12, 1),
                scoring_config_id=config_id,
            )
    finally:
        await engine.dispose()


async def test_cannot_open_season_with_missing_scoring_config(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)

        with pytest.raises(SeasonScoringConfigNotFoundError):
            await service.open_season(
                admin_telegram_id=100,
                name="Осень 2026",
                starts_at=date(2026, 9, 1),
                scoring_config_id=999,
            )
    finally:
        await engine.dispose()


async def test_open_season_rolls_back_previous_close_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )

        def fail_add(self: SeasonRepository, season: Season) -> None:
            del self, season
            raise RuntimeError("forced failure")

        monkeypatch.setattr(SeasonRepository, "add", fail_add)

        with pytest.raises(RuntimeError):
            await service.open_season(
                admin_telegram_id=100,
                name="Зима 2026",
                starts_at=date(2026, 12, 1),
                scoring_config_id=config_id,
            )

        async with session_factory() as session:
            seasons = list((await session.execute(select(Season))).scalars())

        assert len(seasons) == 1
        assert seasons[0].name == "Осень 2026"
        assert seasons[0].status == SeasonStatus.ACTIVE
        assert seasons[0].ends_at is None
    finally:
        await engine.dispose()


async def test_unique_active_season_conflict_becomes_domain_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )

        async def hide_active(self: SeasonRepository) -> Season | None:
            del self
            return None

        monkeypatch.setattr(SeasonRepository, "get_active", hide_active)

        with pytest.raises(SeasonConflictError):
            await service.open_season(
                admin_telegram_id=100,
                name="Зима 2026",
                starts_at=date(2026, 12, 1),
                scoring_config_id=config_id,
            )
    finally:
        await engine.dispose()


async def test_only_one_active_season_exists_after_rotation(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )
        await service.open_season(
            admin_telegram_id=100,
            name="Зима 2026",
            starts_at=date(2026, 12, 1),
            scoring_config_id=config_id,
        )

        async with session_factory() as session:
            active_seasons = list(
                (
                    await session.execute(
                        select(Season).where(Season.status == SeasonStatus.ACTIVE)
                    )
                ).scalars()
            )

        assert [season.name for season in active_seasons] == ["Зима 2026"]
    finally:
        await engine.dispose()


async def test_existing_tournaments_keep_season_binding(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        first = await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )
        async with session_factory() as session:
            tournament = Tournament(
                season_id=first.id,
                tournament_type_id=1,
                date=date(2026, 9, 5),
                status=TournamentStatus.ACTIVE,
            )
            session.add(tournament)
            await session.commit()
            tournament_id = tournament.id

        await service.open_season(
            admin_telegram_id=100,
            name="Зима 2026",
            starts_at=date(2026, 12, 1),
            scoring_config_id=config_id,
        )

        async with session_factory() as session:
            tournament = await session.get(Tournament, tournament_id)

        assert tournament is not None
        assert tournament.season_id == first.id
    finally:
        await engine.dispose()
