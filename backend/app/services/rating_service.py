from datetime import date
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.repositories.rating_repository import RatingHonours, RatingRepository
from app.db.repositories.season_repository import SeasonRepository
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
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def get_rating_for_player(
        self,
        telegram_id: int,
        kind: RatingKind,
        today: date | None = None,
    ) -> RatingResultView:
        business_date = today or self.clock.today()
        async with self.session_factory() as session:
            try:
                player = await require_active_user(UserRepository(session), telegram_id)
            except ActiveUserRequiredError as exc:
                raise RatingNotAllowedError from exc
            title, rows = await self._get_rating(
                rating_repository=RatingRepository(session),
                season_repository=SeasonRepository(session),
                kind=kind,
                today=business_date,
            )
            return RatingResultView(
                title=title,
                rows=rows,
                current_player_id=player.id,
            )

    @staticmethod
    async def _get_rating(
        rating_repository: RatingRepository,
        season_repository: SeasonRepository,
        kind: RatingKind,
        today: date,
    ) -> tuple[str, list[PointsRatingView] | list[KnockoutsRatingView]]:
        honours = await rating_repository.get_rating_honours(today)
        if kind == RatingKind.CURRENT_SEASON:
            season = await season_repository.get_for_date(today)
            if season is None:
                return "Рейтинг — текущий сезон", []
            return (
                "Рейтинг — текущий сезон",
                [
                    points_rating_view(row.__dict__, honours)
                    for row in await rating_repository.get_points_rating(
                        season_id=season.id if season else None,
                    )
                ],
            )
        if kind == RatingKind.ALL_TIME:
            return (
                "Рейтинг — за всё время",
                [
                    points_rating_view(row.__dict__, honours)
                    for row in await rating_repository.get_points_rating()
                ],
            )
        if kind == RatingKind.KNOCKOUTS_CURRENT_SEASON:
            season = await season_repository.get_for_date(today)
            if season is None:
                return "Рейтинг по нокаутам — текущий сезон", []
            return (
                "Рейтинг по нокаутам — текущий сезон",
                [
                    knockouts_rating_view(row.__dict__, honours)
                    for row in await rating_repository.get_knockouts_rating(
                        season_id=season.id if season else None,
                    )
                ],
            )
        return (
            "Рейтинг по нокаутам — за всё время",
            [
                knockouts_rating_view(row.__dict__, honours)
                for row in await rating_repository.get_knockouts_rating()
            ],
        )


def points_rating_view(row: dict[str, object], honours: RatingHonours) -> PointsRatingView:
    player_id = int(row["player_id"])
    return PointsRatingView(
        **row,
        season_champion_titles_count=honours.season_champion_titles_by_player_id.get(
            player_id,
            0,
        ),
    )


def knockouts_rating_view(row: dict[str, object], honours: RatingHonours) -> KnockoutsRatingView:
    player_id = int(row["player_id"])
    return KnockoutsRatingView(
        **row,
        season_champion_titles_count=honours.season_champion_titles_by_player_id.get(
            player_id,
            0,
        ),
        season_knockout_leader_titles_count=(
            honours.season_knockout_leader_titles_by_player_id.get(player_id, 0)
        ),
    )


rating_service = RatingService(SessionFactory)
