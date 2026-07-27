from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.rating_repository import (
    RatingRepository,
)
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto import KnockoutsRatingView, PointsRatingView, RatingResultView
from app.services.user_service import ActiveUserRequiredError, require_active_user


class RatingKind(StrEnum):
    CURRENT_SEASON = "current_season"
    ALL_TIME = "all_time"
    KNOCKOUTS_CURRENT_SEASON = "knockouts_current_season"
    KNOCKOUTS_ALL_TIME = "knockouts_all_time"


class RatingNotAllowedError(ValueError):
    pass


class RatingService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_rating_for_player(
        self,
        telegram_id: int,
        kind: RatingKind,
    ) -> RatingResultView:
        async with self.session_factory() as session:
            try:
                player = await require_active_user(UserRepository(session), telegram_id)
            except ActiveUserRequiredError as exc:
                raise RatingNotAllowedError from exc
            title, rows = await self._get_rating(RatingRepository(session), kind)
            return RatingResultView(
                title=title,
                rows=rows,
                current_player_id=player.id,
            )

    @staticmethod
    async def _get_rating(
        repository: RatingRepository,
        kind: RatingKind,
    ) -> tuple[str, list[PointsRatingView] | list[KnockoutsRatingView]]:
        if kind == RatingKind.CURRENT_SEASON:
            return (
                "Рейтинг — текущий сезон",
                [
                    PointsRatingView(**row.__dict__)
                    for row in await repository.get_points_rating(current_season=True)
                ],
            )
        if kind == RatingKind.ALL_TIME:
            return (
                "Рейтинг — за всё время",
                [
                    PointsRatingView(**row.__dict__)
                    for row in await repository.get_points_rating(current_season=False)
                ],
            )
        if kind == RatingKind.KNOCKOUTS_CURRENT_SEASON:
            return (
                "Рейтинг по нокаутам — текущий сезон",
                [
                    KnockoutsRatingView(**row.__dict__)
                    for row in await repository.get_knockouts_rating(current_season=True)
                ],
            )
        return (
            "Рейтинг по нокаутам — за всё время",
            [
                KnockoutsRatingView(**row.__dict__)
                for row in await repository.get_knockouts_rating(current_season=False)
            ],
        )


rating_service = RatingService(SessionFactory)
