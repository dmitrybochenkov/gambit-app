from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.factories import create_user
from app.db.models import (
    ScoringConfig,
    Season,
    SeasonHallOfFame,
    Tournament,
    TournamentResult,
    TournamentType,
    User,
)
from app.db.models.enums import TournamentStatus, UserRole, UserStatus
from app.services.access_policy import ActiveUserRequiredError, AdminAccessDeniedError
from app.services.player_search import InvalidDisplayNameError
from app.services.user_rename_service import (
    UserRenameNameOccupiedError,
    UserRenameSameNameError,
    UserRenameService,
)


async def create_rename_service(database_path: Path) -> tuple[UserRenameService, object]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return UserRenameService(async_sessionmaker(engine, expire_on_commit=False)), engine


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actor", "error"),
    [
        (None, ActiveUserRequiredError),
        (
            create_user(display_name="Blocked", telegram_id=1, status=UserStatus.BLOCKED),
            ActiveUserRequiredError,
        ),
        (create_user(display_name="Player", telegram_id=1), AdminAccessDeniedError),
        (
            create_user(display_name="Admin", telegram_id=1, role=UserRole.ADMIN),
            AdminAccessDeniedError,
        ),
    ],
)
async def test_user_rename_requires_active_superadmin(
    tmp_path: Path,
    actor: User | None,
    error: type[Exception],
) -> None:
    service, engine = await create_rename_service(tmp_path / "rename.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if actor is not None:
                session.add(actor)
                await session.commit()

        with pytest.raises(error):
            await service.search_users_for_rename(1, "Player")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_user_rename_search_finds_all_roles_and_offline_users(tmp_path: Path) -> None:
    service, engine = await create_rename_service(tmp_path / "rename.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(
                [
                    create_user(
                        display_name="Root",
                        telegram_id=1,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(display_name="Rename Player", telegram_id=10),
                    create_user(
                        display_name="Rename Admin",
                        telegram_id=11,
                        role=UserRole.ADMIN,
                    ),
                    create_user(
                        display_name="Rename Superadmin",
                        telegram_id=12,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(display_name="Rename Offline"),
                ]
            )
            await session.commit()

        results = await service.search_users_for_rename(1, "rename")

        assert [user.display_name for user in results] == [
            "Rename Admin",
            "Rename Offline",
            "Rename Player",
            "Rename Superadmin",
        ]
        assert {user.role for user in results} == {
            UserRole.PLAYER,
            UserRole.ADMIN,
            UserRole.SUPERADMIN,
        }
        assert any(user.telegram_id is None for user in results)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_user_rename_rejects_invalid_occupied_and_same_name(tmp_path: Path) -> None:
    service, engine = await create_rename_service(tmp_path / "rename.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(
                [
                    create_user(
                        display_name="Root",
                        telegram_id=1,
                        role=UserRole.SUPERADMIN,
                    ),
                    create_user(display_name="Иван Иванов"),
                    create_user(display_name="Пётр Петров"),
                ]
            )
            await session.commit()
            target_id = (
                await session.execute(select(User.id).where(User.display_name == "Иван Иванов"))
            ).scalar_one()

        with pytest.raises(InvalidDisplayNameError):
            await service.validate_new_display_name(1, target_id, "   ")
        with pytest.raises(UserRenameSameNameError):
            await service.validate_new_display_name(1, target_id, "иван   иванов")
        with pytest.raises(UserRenameNameOccupiedError):
            await service.validate_new_display_name(1, target_id, "Петр Петров")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_user_rename_confirmation_updates_name_only_and_keeps_relations(
    tmp_path: Path,
) -> None:
    service, engine = await create_rename_service(tmp_path / "rename.db")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            root = create_user(display_name="Root", telegram_id=1, role=UserRole.SUPERADMIN)
            target = create_user(display_name="Иван Иванов", telegram_id=10, role=UserRole.ADMIN)
            session.add_all([root, target])
            await session.flush()
            config = ScoringConfig(id=1)
            season = Season(
                name="Лето 2026",
                starts_at=date(2026, 6, 1),
                scoring_config_id=1,
            )
            tournament_type = TournamentType(
                id=1,
                code="classic",
                name="Классика",
                short_name="Classic",
            )
            tournament = Tournament(
                season_id=1,
                tournament_type_id=1,
                date=date(2026, 7, 1),
                status=TournamentStatus.CLOSED,
                tournament_fund=None,
            )
            session.add_all([config, season, tournament_type, tournament])
            await session.flush()
            session.add_all(
                [
                    TournamentResult(
                        tournament_id=tournament.id,
                        player_id=target.id,
                        tournament_points=Decimal("100"),
                    ),
                    SeasonHallOfFame(
                        season_id=season.id,
                        champion_player_id=target.id,
                        knockout_player_id=target.id,
                        updated_by_user_id=root.id,
                    ),
                ]
            )
            await session.commit()
            target_id = target.id
            root_id = root.id

        renamed = await service.rename_user(
            1,
            target_id,
            "  Иван   Петров ",
            "Иван Иванов",
        )

        assert renamed.id == target_id
        assert renamed.display_name == "Иван Петров"
        assert renamed.telegram_id == 10
        assert renamed.role == UserRole.ADMIN
        assert renamed.status == UserStatus.ACTIVE

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stored = await session.get(User, target_id)
            result_player_id = (
                await session.execute(select(TournamentResult.player_id))
            ).scalar_one()
            hall_of_fame = (await session.execute(select(SeasonHallOfFame))).scalar_one()

        assert stored is not None
        assert stored.display_name == "Иван Петров"
        assert stored.display_name_normalized == "иван петров"
        assert stored.telegram_id == 10
        assert stored.role == UserRole.ADMIN
        assert stored.status == UserStatus.ACTIVE
        assert result_player_id == target_id
        assert hall_of_fame.champion_player_id == target_id
        assert hall_of_fame.knockout_player_id == target_id
        assert hall_of_fame.updated_by_user_id == root_id
    finally:
        await engine.dispose()
