from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.enums import PlayerStatus
from app.db.repositories.player_repository import PlayerRepository
from app.db.repositories.profile_repository import (
    ProfileRepository,
)
from app.db.session import SessionFactory
from app.services.dto import PlayerProfileView


class ProfileKind(StrEnum):
    CURRENT_SEASON = "current_season"
    ALL_TIME = "all_time"


class ProfileNotAllowedError(ValueError):
    pass


class ProfileService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_profile(
        self,
        telegram_id: int,
        kind: ProfileKind,
    ) -> tuple[str, PlayerProfileView | None]:
        async with self.session_factory() as session:
            return await self._get_profile(ProfileRepository(session), telegram_id, kind)

    async def get_profile_for_player(
        self,
        telegram_id: int,
        kind: ProfileKind,
    ) -> tuple[str, PlayerProfileView | None]:
        async with self.session_factory() as session:
            player = await PlayerRepository(session).get_by_telegram_id(telegram_id)
            if player is None or player.status != PlayerStatus.ACTIVE:
                raise ProfileNotAllowedError
            return await self._get_profile(ProfileRepository(session), telegram_id, kind)

    @staticmethod
    async def _get_profile(
        repository: ProfileRepository,
        telegram_id: int,
        kind: ProfileKind,
    ) -> tuple[str, PlayerProfileView | None]:
        if kind == ProfileKind.CURRENT_SEASON:
            stats = await repository.get_player_stats(
                telegram_id=telegram_id,
                current_season=True,
            )
            return (
                "Твой профиль — текущий сезон",
                PlayerProfileView(**stats.__dict__) if stats else None,
            )
        stats = await repository.get_player_stats(
            telegram_id=telegram_id,
            current_season=False,
        )
        return (
            "Твой профиль — за всё время",
            PlayerProfileView(**stats.__dict__) if stats else None,
        )


profile_service = ProfileService(SessionFactory)
