from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.rating_repository import (
    KnockoutsRatingRow,
    PointsRatingRow,
    RatingRepository,
)
from app.db.session import SessionFactory


class RatingKind(StrEnum):
    CURRENT_SEASON = "current_season"
    ALL_TIME = "all_time"
    KNOCKOUTS_CURRENT_SEASON = "knockouts_current_season"
    KNOCKOUTS_ALL_TIME = "knockouts_all_time"


class RatingService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_rating(
        self,
        kind: RatingKind,
    ) -> tuple[str, list[PointsRatingRow] | list[KnockoutsRatingRow]]:
        async with self.session_factory() as session:
            repository = RatingRepository(session)
            if kind == RatingKind.CURRENT_SEASON:
                return (
                    "Рейтинг — текущий сезон",
                    await repository.get_points_rating(current_season=True),
                )
            if kind == RatingKind.ALL_TIME:
                return (
                    "Рейтинг — за всё время",
                    await repository.get_points_rating(current_season=False),
                )
            if kind == RatingKind.KNOCKOUTS_CURRENT_SEASON:
                return (
                    "Рейтинг по нокаутам — текущий сезон",
                    await repository.get_knockouts_rating(current_season=True),
                )
            return (
                "Рейтинг по нокаутам — за всё время",
                await repository.get_knockouts_rating(current_season=False),
            )


rating_service = RatingService(SessionFactory)
