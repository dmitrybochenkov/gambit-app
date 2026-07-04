from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.enums import PlayerStatus
from app.services.player_service import IdentityAlreadyExistsError, PlayerService


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
