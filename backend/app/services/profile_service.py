from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.profile_repository import (
    PlayerProfileStats,
    ProfileRepository,
)
from app.db.session import SessionFactory


class ProfileKind(StrEnum):
    CURRENT_SEASON = "current_season"
    ALL_TIME = "all_time"


class ProfileService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_profile(
        self,
        telegram_id: int,
        kind: ProfileKind,
    ) -> tuple[str, PlayerProfileStats | None]:
        async with self.session_factory() as session:
            repository = ProfileRepository(session)
            if kind == ProfileKind.CURRENT_SEASON:
                return (
                    "Твой профиль — текущий сезон",
                    await repository.get_player_stats(
                        telegram_id=telegram_id,
                        current_season=True,
                    ),
                )
            return (
                "Твой профиль — за всё время",
                await repository.get_player_stats(
                    telegram_id=telegram_id,
                    current_season=False,
                ),
            )


profile_service = ProfileService(SessionFactory)
