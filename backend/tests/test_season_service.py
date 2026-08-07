from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.common.clock import FixedClock
from app.db.base import Base
from app.db.factories import create_user
from app.db.models import AdminPrompt, ScoringConfig, Season, Tournament
from app.db.models.enums import (
    AdminPromptStatus,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.db.repositories.season_repository import SeasonRepository
from app.services.dto.seasons import SeasonLifecycleStateView
from app.services.season_service import (
    SeasonConflictError,
    SeasonDateOverlapError,
    SeasonNameAlreadyExistsError,
    SeasonNameInvalidError,
    SeasonProposalAlreadyResolvedError,
    SeasonScheduledConflictError,
    SeasonScoringConfigAmbiguousError,
    SeasonScoringConfigNotFoundError,
    SeasonService,
    SeasonStartDateError,
    season_lifecycle_state,
    season_name_for_date,
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
    assert season_name_for_date(date(2026, 7, 28)) == "Лето 2026"
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
            ends_at=date(2026, 8, 31),
            today=date(2026, 8, 1),
        )
        == SeasonLifecycleStateView.CURRENT
    )
    assert (
        season_lifecycle_state(
            starts_at=date(2026, 8, 1),
            ends_at=date(2026, 8, 31),
            today=date(2026, 8, 31),
        )
        == SeasonLifecycleStateView.CURRENT
    )
    assert (
        season_lifecycle_state(
            starts_at=date(2026, 8, 1),
            ends_at=date(2026, 8, 31),
            today=date(2026, 9, 1),
        )
        == SeasonLifecycleStateView.COMPLETED
    )
    assert (
        season_lifecycle_state(
            starts_at=date(2026, 8, 1),
            ends_at=None,
            today=date(2026, 9, 1),
        )
        == SeasonLifecycleStateView.CURRENT
    )


async def test_create_season_proposal_uses_tomorrow_and_creates_no_season(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)

        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )

        assert proposal.name == "Лето 2026"
        assert proposal.starts_at == date(2026, 7, 28)
        assert proposal.scoring_config_id == config_id

        async with session_factory() as session:
            seasons = list((await session.execute(select(Season))).scalars())
            prompts = list((await session.execute(select(AdminPrompt))).scalars())

        assert seasons == []
        assert len(prompts) == 1
        assert prompts[0].key == "season:1"
        assert prompts[0].scope_key == "season"
        assert prompts[0].status == AdminPromptStatus.PENDING
    finally:
        await engine.dispose()


async def test_create_season_proposal_reuses_single_pending_scope(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)

        first = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )
        second = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 28),
        )

        assert second.id == first.id
        assert second.starts_at == first.starts_at

        await service.cancel_season_proposal(admin_telegram_id=100, prompt_id=first.id)
        third = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 28),
        )

        assert third.id != first.id
        async with session_factory() as session:
            prompts = list(
                (await session.execute(select(AdminPrompt).order_by(AdminPrompt.id))).scalars()
            )

        assert [(prompt.key, prompt.scope_key, prompt.status) for prompt in prompts] == [
            ("season:1", "season", AdminPromptStatus.CANCELLED),
            ("season:2", "season", AdminPromptStatus.PENDING),
        ]
    finally:
        await engine.dispose()


async def test_create_season_proposal_requires_scoring_config(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
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
            await session.commit()

        with pytest.raises(SeasonScoringConfigNotFoundError):
            await service.create_season_proposal(
                admin_telegram_id=100,
                today=date(2026, 7, 27),
            )
    finally:
        await engine.dispose()


async def test_create_season_proposal_rejects_ambiguous_scoring_configs(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        async with session_factory() as session:
            session.add(ScoringConfig())
            await session.commit()

        with pytest.raises(SeasonScoringConfigAmbiguousError):
            await service.create_season_proposal(
                admin_telegram_id=100,
                today=date(2026, 7, 27),
            )
    finally:
        await engine.dispose()


async def test_create_season_proposal_copies_active_season_scoring_config(
    tmp_path: Path,
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
        async with session_factory() as session:
            session.add(ScoringConfig())
            await session.commit()

        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 12, 1),
        )

        assert proposal.scoring_config_id == config_id
    finally:
        await engine.dispose()


async def test_update_season_proposal_name_preserves_start_date(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )

        updated = await service.update_season_proposal_name(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            name="  Осень   2026 ",
        )

        assert updated.name == "Осень 2026"
        assert updated.starts_at == date(2026, 7, 28)
        assert updated.scoring_config_id == proposal.scoring_config_id
    finally:
        await engine.dispose()


async def test_update_season_proposal_rejects_blank_name(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )

        with pytest.raises(SeasonNameInvalidError):
            await service.update_season_proposal_name(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                name="   ",
            )
    finally:
        await engine.dispose()


async def test_update_season_proposal_start_date_preserves_name(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )

        updated = await service.update_season_proposal_start_date(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            starts_at=date(2026, 9, 1),
        )

        assert updated.name == "Лето 2026"
        assert updated.starts_at == date(2026, 9, 1)
        assert updated.scoring_config_id == proposal.scoring_config_id
    finally:
        await engine.dispose()


async def test_confirm_season_proposal_opens_season(tmp_path: Path) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        resolved_at = datetime(2026, 7, 28, 12, 30)
        service = SeasonService(session_factory, clock=FixedClock(resolved_at))
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )

        season = await service.confirm_season_proposal(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            today=date(2026, 7, 28),
        )

        assert season.name == "Лето 2026"
        assert season.starts_at == date(2026, 7, 28)
        assert season.lifecycle_state == SeasonLifecycleStateView.CURRENT

        async with session_factory() as session:
            prompt = await session.get(AdminPrompt, proposal.id)
            seasons = list((await session.execute(select(Season))).scalars())

        assert prompt is not None
        assert prompt.status == AdminPromptStatus.CONFIRMED
        assert prompt.resolved_at == resolved_at
        assert prompt.resolved_by_user_id == 1
        assert len(seasons) == 1
    finally:
        await engine.dispose()


async def test_confirm_season_proposal_rejects_start_date_in_past(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )
        await service.update_season_proposal_start_date(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            starts_at=date(2026, 7, 28),
        )

        with pytest.raises(SeasonStartDateError):
            await service.confirm_season_proposal(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                today=date(2026, 7, 29),
            )

        async with session_factory() as session:
            prompt = await session.get(AdminPrompt, proposal.id)
            seasons = list((await session.execute(select(Season))).scalars())

        assert prompt is not None
        assert prompt.status == AdminPromptStatus.PENDING
        assert seasons == []
    finally:
        await engine.dispose()


async def test_confirm_future_season_proposal_schedules_next_season_and_closes_current(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        active = await service.open_season(
            admin_telegram_id=100,
            name="Осень 2026",
            starts_at=date(2026, 9, 1),
            scoring_config_id=config_id,
        )
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 12, 1),
        )
        await service.update_season_proposal_name(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            name="Зима 2026",
        )

        created = await service.confirm_season_proposal(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            today=date(2026, 12, 1),
        )

        async with session_factory() as session:
            prompt = await session.get(AdminPrompt, proposal.id)
            seasons = list(
                (await session.execute(select(Season).order_by(Season.starts_at))).scalars()
            )

        assert prompt is not None
        assert prompt.status == AdminPromptStatus.CONFIRMED
        assert created.name == "Зима 2026"
        assert created.starts_at == date(2026, 12, 2)
        assert [(season.id, season.ends_at) for season in seasons] == [
            (active.id, date(2026, 12, 1)),
            (created.id, None),
        ]
    finally:
        await engine.dispose()


async def test_confirm_season_proposal_rejects_same_day_start_when_active_exists(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        active = await service.open_season(
            admin_telegram_id=100,
            name="Лето 2026",
            starts_at=date(2026, 7, 1),
            scoring_config_id=config_id,
        )
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )
        await service.update_season_proposal_name(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            name="Осень 2026",
        )

        with pytest.raises(SeasonConflictError):
            await service.confirm_season_proposal(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                today=date(2026, 7, 28),
            )

        async with session_factory() as session:
            prompt = await session.get(AdminPrompt, proposal.id)
            seasons = list((await session.execute(select(Season))).scalars())

        assert prompt is not None
        assert prompt.status == AdminPromptStatus.PENDING
        assert [(season.id, season.ends_at) for season in seasons] == [(active.id, None)]
    finally:
        await engine.dispose()


async def test_confirm_season_proposal_rejects_second_scheduled_season(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    Season(
                        name="Лето 2026",
                        scoring_config_id=config_id,
                        starts_at=date(2026, 7, 1),
                        ends_at=date(2026, 8, 9),
                    ),
                    Season(
                        name="Осень 2026",
                        scoring_config_id=config_id,
                        starts_at=date(2026, 8, 10),
                        ends_at=None,
                    ),
                ]
            )
            await session.commit()

        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )
        await service.update_season_proposal_name(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            name="Зима 2026",
        )
        await service.update_season_proposal_start_date(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            starts_at=date(2026, 12, 1),
        )

        with pytest.raises(SeasonScheduledConflictError):
            await service.confirm_season_proposal(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                today=date(2026, 7, 28),
            )

        async with session_factory() as session:
            prompt = await session.get(AdminPrompt, proposal.id)
            seasons = list(
                (await session.execute(select(Season).order_by(Season.starts_at))).scalars()
            )

        assert prompt is not None
        assert prompt.status == AdminPromptStatus.PENDING
        assert [(season.name, season.ends_at) for season in seasons] == [
            ("Лето 2026", date(2026, 8, 9)),
            ("Осень 2026", None),
        ]
    finally:
        await engine.dispose()


async def test_duplicate_season_proposal_confirmation_is_rejected(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )
        await service.confirm_season_proposal(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            today=date(2026, 7, 28),
        )

        with pytest.raises(SeasonProposalAlreadyResolvedError):
            await service.confirm_season_proposal(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                today=date(2026, 7, 28),
            )

        async with session_factory() as session:
            seasons = list((await session.execute(select(Season))).scalars())

        assert len(seasons) == 1
    finally:
        await engine.dispose()


async def test_confirmed_season_proposal_cannot_be_edited_or_cancelled(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )
        await service.confirm_season_proposal(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            today=date(2026, 7, 28),
        )

        with pytest.raises(SeasonProposalAlreadyResolvedError):
            await service.update_season_proposal_name(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                name="Осень 2026",
            )
        with pytest.raises(SeasonProposalAlreadyResolvedError):
            await service.update_season_proposal_start_date(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                starts_at=date(2026, 9, 1),
            )
        with pytest.raises(SeasonProposalAlreadyResolvedError):
            await service.cancel_season_proposal(admin_telegram_id=100, prompt_id=proposal.id)
    finally:
        await engine.dispose()


async def test_cancel_season_proposal_creates_no_season_and_blocks_confirmation(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        resolved_at = datetime(2026, 7, 28, 13, 0)
        service = SeasonService(session_factory, clock=FixedClock(resolved_at))
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )

        await service.cancel_season_proposal(admin_telegram_id=100, prompt_id=proposal.id)

        with pytest.raises(SeasonProposalAlreadyResolvedError):
            await service.confirm_season_proposal(admin_telegram_id=100, prompt_id=proposal.id)

        async with session_factory() as session:
            prompt = await session.get(AdminPrompt, proposal.id)
            seasons = list((await session.execute(select(Season))).scalars())

        assert prompt is not None
        assert prompt.status == AdminPromptStatus.CANCELLED
        assert prompt.resolved_at == resolved_at
        assert prompt.resolved_by_user_id == 1
        assert seasons == []
    finally:
        await engine.dispose()


async def test_cancelled_season_proposal_cannot_be_edited_or_cancelled_again(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )

        await service.cancel_season_proposal(admin_telegram_id=100, prompt_id=proposal.id)

        with pytest.raises(SeasonProposalAlreadyResolvedError):
            await service.update_season_proposal_name(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                name="Осень 2026",
            )
        with pytest.raises(SeasonProposalAlreadyResolvedError):
            await service.update_season_proposal_start_date(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                starts_at=date(2026, 9, 1),
            )
        with pytest.raises(SeasonProposalAlreadyResolvedError):
            await service.cancel_season_proposal(admin_telegram_id=100, prompt_id=proposal.id)
    finally:
        await engine.dispose()


async def test_failed_season_proposal_confirmation_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        await seed_admin_and_config(session_factory)
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )

        def fail_add(self: SeasonRepository, season: Season) -> None:
            del self, season
            raise RuntimeError("forced failure")

        monkeypatch.setattr(SeasonRepository, "add", fail_add)

        with pytest.raises(RuntimeError):
            await service.confirm_season_proposal(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                today=date(2026, 7, 28),
            )

        async with session_factory() as session:
            prompt = await session.get(AdminPrompt, proposal.id)
            seasons = list((await session.execute(select(Season))).scalars())

        assert prompt is not None
        assert prompt.status == AdminPromptStatus.PENDING
        assert seasons == []
    finally:
        await engine.dispose()


async def test_failed_future_season_confirmation_restores_current_season(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        await service.open_season(
            admin_telegram_id=100,
            name="Лето 2026",
            starts_at=date(2026, 7, 1),
            scoring_config_id=config_id,
        )
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )
        await service.update_season_proposal_start_date(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            starts_at=date(2026, 8, 10),
        )
        await service.update_season_proposal_name(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            name="Осень 2026",
        )

        def fail_add(self: SeasonRepository, season: Season) -> None:
            del self, season
            raise RuntimeError("forced failure")

        monkeypatch.setattr(SeasonRepository, "add", fail_add)

        with pytest.raises(RuntimeError):
            await service.confirm_season_proposal(
                admin_telegram_id=100,
                prompt_id=proposal.id,
                today=date(2026, 7, 28),
            )

        async with session_factory() as session:
            prompt = await session.get(AdminPrompt, proposal.id)
            seasons = list((await session.execute(select(Season))).scalars())

        assert prompt is not None
        assert prompt.status == AdminPromptStatus.PENDING
        assert [(season.name, season.ends_at) for season in seasons] == [("Лето 2026", None)]
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

        assert second.lifecycle_state == SeasonLifecycleStateView.CURRENT
        assert second.ends_at is None
        assert [(season.id, season.ends_at) for season in seasons] == [
            (first.id, date(2026, 11, 30)),
            (second.id, None),
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

        active = await service.get_active_season(today=date(2026, 9, 1))
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
        assert seasons[0].ends_at is None
    finally:
        await engine.dispose()


async def test_open_season_rejects_overlapping_season_without_current_match(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        async with session_factory() as session:
            session.add(
                Season(
                    name="Лето 2026",
                    scoring_config_id=config_id,
                    starts_at=date(2026, 7, 1),
                    ends_at=date(2026, 8, 31),
                )
            )
            await session.commit()

        with pytest.raises(SeasonDateOverlapError):
            await service.open_season(
                admin_telegram_id=100,
                name="Осень 2026",
                starts_at=date(2026, 8, 15),
                scoring_config_id=config_id,
            )
    finally:
        await engine.dispose()


async def test_only_one_open_ended_season_exists_after_rotation(tmp_path: Path) -> None:
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
            open_ended_seasons = list(
                (await session.execute(select(Season).where(Season.ends_at.is_(None)))).scalars()
            )

        assert [season.name for season in open_ended_seasons] == ["Зима 2026"]
    finally:
        await engine.dispose()


async def test_current_and_scheduled_seasons_are_resolved_from_dates(
    tmp_path: Path,
) -> None:
    service, session_factory, engine = await create_season_service(tmp_path / "season.db")
    try:
        config_id = await seed_admin_and_config(session_factory)
        active = await service.open_season(
            admin_telegram_id=100,
            name="Лето 2026",
            starts_at=date(2026, 7, 1),
            scoring_config_id=config_id,
        )
        proposal = await service.create_season_proposal(
            admin_telegram_id=100,
            today=date(2026, 7, 27),
        )
        await service.update_season_proposal_name(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            name="Осень 2026",
        )
        await service.update_season_proposal_start_date(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            starts_at=date(2026, 8, 10),
        )
        scheduled = await service.confirm_season_proposal(
            admin_telegram_id=100,
            prompt_id=proposal.id,
            today=date(2026, 7, 28),
        )

        async with session_factory() as session:
            repository = SeasonRepository(session)
            assert (await repository.get_for_date(date(2026, 8, 9))).id == active.id
            assert (await repository.get_scheduled_after(date(2026, 8, 9))).id == scheduled.id
            current = await repository.get_for_date(date(2026, 8, 10))
            seasons = list(
                (await session.execute(select(Season).order_by(Season.starts_at))).scalars()
            )

        assert current is not None
        assert current.id == scheduled.id
        assert [(season.name, season.ends_at) for season in seasons] == [
            ("Лето 2026", date(2026, 8, 9)),
            ("Осень 2026", None),
        ]
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
