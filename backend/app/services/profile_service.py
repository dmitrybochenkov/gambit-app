from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.profile_repository import (
    ProfileRepository,
)
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto import PlayerProfileView
from app.services.user_service import ActiveUserRequiredError, require_active_user


class ProfileKind(StrEnum):
    CURRENT_SEASON = "current_season"
    ALL_TIME = "all_time"


class ProfileNotAllowedError(ValueError):
    pass


class ProfileService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_profile_for_player(
        self,
        telegram_id: int,
        kind: ProfileKind,
        today: date | None = None,
    ) -> tuple[str, PlayerProfileView | None]:
        business_date = today or date.today()
        async with self.session_factory() as session:
            try:
                user = await require_active_user(UserRepository(session), telegram_id)
            except ActiveUserRequiredError as exc:
                raise ProfileNotAllowedError from exc
            return await self._get_profile(
                profile_repository=ProfileRepository(session),
                season_repository=SeasonRepository(session),
                telegram_id=telegram_id,
                display_name=user.display_name,
                kind=kind,
                today=business_date,
            )

    @staticmethod
    async def _get_profile(
        profile_repository: ProfileRepository,
        season_repository: SeasonRepository,
        telegram_id: int,
        display_name: str,
        kind: ProfileKind,
        today: date,
    ) -> tuple[str, PlayerProfileView | None]:
        if kind == ProfileKind.CURRENT_SEASON:
            season = await season_repository.get_for_date(today)
            if season is None:
                return (
                    "Твой профиль — текущий сезон",
                    empty_profile(display_name),
                )
            stats = await profile_repository.get_player_stats(
                telegram_id=telegram_id,
                season_id=season.id,
            )
            return (
                "Твой профиль — текущий сезон",
                PlayerProfileView(**stats.__dict__) if stats else None,
            )
        stats = await profile_repository.get_player_stats(
            telegram_id=telegram_id,
        )
        return (
            "Твой профиль — за всё время",
            PlayerProfileView(**stats.__dict__) if stats else None,
        )


def empty_profile(display_name: str) -> PlayerProfileView:
    return PlayerProfileView(
        display_name=display_name,
        total_points=Decimal("0"),
        knockout_points=Decimal("0"),
        knockouts_count=0,
        big_knockouts_count=0,
        tournaments_count=0,
        first_places_count=0,
        second_places_count=0,
        third_places_count=0,
        fourth_places_count=0,
        fifth_places_count=0,
    )


profile_service = ProfileService(SessionFactory)
