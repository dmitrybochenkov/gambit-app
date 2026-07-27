from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.factories import create_player
from app.db.models import Player, RegistrationMatch
from app.db.models.enums import PlayerRole, PlayerStatus
from app.services.dto import PlayerStatusView
from app.services.player_service import (
    AdminAccessDeniedError,
    IdentityAlreadyExistsError,
    PlayerService,
)


async def create_player_service(database_path: Path) -> tuple[PlayerService, AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return PlayerService(session_factory), engine


async def test_submit_pending_registration(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        player = await service.submit_registration(
            telegram_id=100,
            display_name="Иван Иванов",
        )

        assert player.status == PlayerStatusView.PENDING
        assert player.display_name == "Иван Иванов"
        stored_player = await service.get_by_telegram_id(100)
        assert stored_player is not None
        assert stored_player.display_name == "Иван Иванов"
    finally:
        await engine.dispose()


async def test_registration_identity_must_be_unique(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        await service.submit_registration(
            telegram_id=100,
            display_name="Ace",
        )

        with pytest.raises(IdentityAlreadyExistsError) as error:
            await service.submit_registration(
                telegram_id=200,
                display_name="Ace",
            )

        assert error.value.field == "display_name"
    finally:
        await engine.dispose()


async def test_registration_creates_historical_match_before_approval(
    tmp_path: Path,
) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            historical_player = create_player(
                telegram_id=-1,
                display_name="Исторический Игрок",
                status=PlayerStatus.ACTIVE,
            )
            session.add(historical_player)
            await session.commit()

        await service.validate_unique_identity(
            telegram_id=100,
            display_name="Исторический Игрок",
        )
        pending_player = await service.submit_registration(
            telegram_id=100,
            display_name="Исторический Игрок",
        )

        assert pending_player.status == PlayerStatusView.PENDING
        assert pending_player.telegram_id == 100
        stored_player = await service.get_by_telegram_id(100)
        assert stored_player is not None
        assert stored_player.display_name == "Исторический Игрок"
        async with session_factory() as session:
            historical = await session.get(Player, historical_player.id)
            assert historical is not None
            assert historical.telegram_id == -1

            match = (await session.execute(select(RegistrationMatch))).scalar_one()
            assert match.pending_player_id == pending_player.id
            assert match.historical_player_id == historical_player.id
            assert match.score == 100
    finally:
        await engine.dispose()


async def test_approval_merges_best_historical_match(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        admin = await service.submit_registration(
            telegram_id=100,
            display_name="Админ Первый",
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            stored_admin = await session.get(Player, admin.id)
            assert stored_admin is not None
            stored_admin.status = PlayerStatus.ACTIVE
            stored_admin.role = PlayerRole.SUPERADMIN
            historical_player = create_player(
                telegram_id=-1,
                display_name="Дима Боченков",
                status=PlayerStatus.ACTIVE,
            )
            session.add(historical_player)
            await session.commit()

        pending_player = await service.submit_registration(
            telegram_id=200,
            display_name="Дима Боченкав",
        )

        approved = await service.approve_registration(
            admin_telegram_id=100,
            player_id=pending_player.id,
        )
        approved_player = approved.player

        assert approved_player.id == historical_player.id
        assert approved_player.telegram_id == 200
        assert approved_player.status == PlayerStatusView.ACTIVE
        assert approved_player.display_name == "Дима Боченков"
        assert [admin.telegram_id for admin in approved.admins] == [100]
        assert await service.get_by_telegram_id(200) is not None

        async with session_factory() as session:
            removed_pending = await session.get(Player, pending_player.id)
            assert removed_pending is None
    finally:
        await engine.dispose()


async def test_approval_merges_selected_historical_match(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        admin = await service.submit_registration(
            telegram_id=100,
            display_name="Админ Первый",
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            stored_admin = await session.get(Player, admin.id)
            assert stored_admin is not None
            stored_admin.status = PlayerStatus.ACTIVE
            stored_admin.role = PlayerRole.SUPERADMIN
            first_historical_player = create_player(
                telegram_id=-1,
                display_name="Дима Боченков",
                status=PlayerStatus.ACTIVE,
            )
            second_historical_player = create_player(
                telegram_id=-2,
                display_name="Дима Боченкав",
                status=PlayerStatus.ACTIVE,
            )
            session.add_all([first_historical_player, second_historical_player])
            await session.commit()

        pending_player = await service.submit_registration(
            telegram_id=200,
            display_name="Дима Боченкав",
        )

        approved = await service.approve_registration(
            admin_telegram_id=100,
            player_id=pending_player.id,
            historical_player_id=second_historical_player.id,
        )

        assert approved.player.id == second_historical_player.id
        assert approved.player.telegram_id == 200
        assert await service.get_by_telegram_id(200) is not None

        async with session_factory() as session:
            first_historical = await session.get(Player, first_historical_player.id)
            assert first_historical is not None
            assert first_historical.telegram_id == -1
    finally:
        await engine.dispose()


async def test_approval_can_ignore_historical_match(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        admin = await service.submit_registration(
            telegram_id=100,
            display_name="Админ Первый",
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            stored_admin = await session.get(Player, admin.id)
            assert stored_admin is not None
            stored_admin.status = PlayerStatus.ACTIVE
            stored_admin.role = PlayerRole.SUPERADMIN
            historical_player = create_player(
                telegram_id=-1,
                display_name="Дима Боченков",
                status=PlayerStatus.ACTIVE,
            )
            session.add(historical_player)
            await session.commit()

        pending_player = await service.submit_registration(
            telegram_id=200,
            display_name="Дима Боченкав",
        )

        approved = await service.approve_registration(
            admin_telegram_id=100,
            player_id=pending_player.id,
            use_registration_match=False,
        )
        approved_player = approved.player

        assert approved_player.id == pending_player.id
        assert approved_player.telegram_id == 200
        assert approved_player.status == PlayerStatusView.ACTIVE

        async with session_factory() as session:
            historical = await session.get(Player, historical_player.id)
            assert historical is not None
            assert historical.telegram_id == -1
    finally:
        await engine.dispose()


async def test_rejection_deletes_pending_registration(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        admin = await service.submit_registration(
            telegram_id=100,
            display_name="Админ Первый",
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            stored_admin = await session.get(Player, admin.id)
            assert stored_admin is not None
            stored_admin.status = PlayerStatus.ACTIVE
            stored_admin.role = PlayerRole.SUPERADMIN
            historical_player = create_player(
                telegram_id=-1,
                display_name="Исторический Игрок",
                status=PlayerStatus.ACTIVE,
            )
            session.add(historical_player)
            await session.commit()

        pending_player = await service.submit_registration(
            telegram_id=200,
            display_name="Исторический Игрок",
        )

        rejected = await service.reject_registration(
            admin_telegram_id=100,
            player_id=pending_player.id,
        )

        assert rejected.player.telegram_id == 200
        assert [admin.telegram_id for admin in rejected.admins] == [100]
        assert await service.get_by_telegram_id(200) is None
        async with session_factory() as session:
            removed_pending = await session.get(Player, pending_player.id)
            matches = (await session.execute(select(RegistrationMatch))).scalars().all()
            assert removed_pending is None
            assert matches == []
    finally:
        await engine.dispose()


async def test_superadmin_can_approve_registration(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        admin = await service.submit_registration(
            telegram_id=100,
            display_name="Админ Первый",
        )
        player = await service.submit_registration(
            telegram_id=200,
            display_name="Игрок Второй",
        )

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            stored_admin = await session.get(Player, admin.id)
            assert stored_admin is not None
            stored_admin.status = PlayerStatus.ACTIVE
            stored_admin.role = PlayerRole.SUPERADMIN
            await session.commit()

        approved = await service.approve_registration(
            admin_telegram_id=100,
            player_id=player.id,
        )

        assert approved.player.status == PlayerStatusView.ACTIVE
        async with session_factory() as session:
            stored_player = await session.get(Player, player.id)
            assert stored_player is not None
            assert stored_player.approved_by_admin_id == admin.id
            assert stored_player.approved_at is not None
    finally:
        await engine.dispose()


async def test_regular_player_cannot_review_registration(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        reviewer = await service.submit_registration(
            telegram_id=100,
            display_name="Игрок Первый",
        )
        player = await service.submit_registration(
            telegram_id=200,
            display_name="Игрок Второй",
        )

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            stored_reviewer = (
                await session.execute(select(Player).where(Player.id == reviewer.id))
            ).scalar_one()
            stored_reviewer.status = PlayerStatus.ACTIVE
            await session.commit()

        with pytest.raises(AdminAccessDeniedError):
            await service.approve_registration(
                admin_telegram_id=100,
                player_id=player.id,
            )
    finally:
        await engine.dispose()


async def test_superadmin_can_promote_active_player_to_admin(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        superadmin = await service.submit_registration(
            telegram_id=100,
            display_name="Админ Первый",
        )
        player = await service.submit_registration(
            telegram_id=200,
            display_name="Игрок Второй",
        )

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            stored_superadmin = await session.get(Player, superadmin.id)
            stored_player = await session.get(Player, player.id)
            assert stored_superadmin is not None
            assert stored_player is not None
            stored_superadmin.status = PlayerStatus.ACTIVE
            stored_superadmin.role = PlayerRole.SUPERADMIN
            stored_player.status = PlayerStatus.ACTIVE
            session.add(
                create_player(
                    telegram_id=-1,
                    display_name="Исторический Игрок",
                    status=PlayerStatus.ACTIVE,
                    role=PlayerRole.USER,
                )
            )
            await session.commit()

        candidates = await service.list_admin_candidates_for_superadmin(100)
        assert [candidate.id for candidate in candidates] == [player.id]

        promoted = await service.add_admin(
            superadmin_telegram_id=100,
            player_id=player.id,
        )

        assert promoted.role.value == PlayerRole.ADMIN.value
        assert promoted.telegram_id == 200
        candidates = await service.list_admin_candidates_for_superadmin(100)
        assert candidates == []
    finally:
        await engine.dispose()
