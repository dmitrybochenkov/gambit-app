from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Player
from app.db.models.enums import PlayerRole, PlayerStatus
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
            full_name="Иван Иванов",
            nickname="Ace",
        )

        assert player.status == PlayerStatus.PENDING
        assert player.display_name == "Иван Иванов (Ace)"
        stored_player = await service.get_by_telegram_id(100)
        assert stored_player is not None
        assert stored_player.nickname == "Ace"
    finally:
        await engine.dispose()


async def test_registration_identity_must_be_unique(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        await service.submit_registration(
            telegram_id=100,
            full_name="Иван Иванов",
            nickname="Ace",
        )

        with pytest.raises(IdentityAlreadyExistsError) as error:
            await service.submit_registration(
                telegram_id=200,
                full_name="Петр Петров",
                nickname="Ace",
            )

        assert error.value.field == "nickname"
    finally:
        await engine.dispose()


async def test_registration_can_claim_historical_player(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            historical_player = Player(
                telegram_id=-1,
                full_name="Исторический Игрок",
                status=PlayerStatus.ACTIVE,
            )
            session.add(historical_player)
            await session.commit()

        await service.validate_unique_identity(
            telegram_id=100,
            full_name="Исторический Игрок",
            nickname=None,
        )
        claimed_player = await service.submit_registration(
            telegram_id=100,
            full_name="Исторический Игрок",
            nickname=None,
        )

        assert claimed_player.status == PlayerStatus.PENDING
        assert claimed_player.telegram_id == 100
        stored_player = await service.get_by_telegram_id(100)
        assert stored_player is not None
        assert stored_player.full_name == "Исторический Игрок"
    finally:
        await engine.dispose()


async def test_superadmin_can_approve_registration(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        admin = await service.submit_registration(
            telegram_id=100,
            full_name="Админ Первый",
            nickname=None,
        )
        player = await service.submit_registration(
            telegram_id=200,
            full_name="Игрок Второй",
            nickname=None,
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

        assert approved.status == PlayerStatus.ACTIVE
        assert approved.approved_by_admin_id == admin.id
        assert approved.approved_at is not None
    finally:
        await engine.dispose()


async def test_regular_player_cannot_review_registration(tmp_path: Path) -> None:
    service, engine = await create_player_service(tmp_path / "players.db")
    try:
        reviewer = await service.submit_registration(
            telegram_id=100,
            full_name="Игрок Первый",
            nickname=None,
        )
        player = await service.submit_registration(
            telegram_id=200,
            full_name="Игрок Второй",
            nickname=None,
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
