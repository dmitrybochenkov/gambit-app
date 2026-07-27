from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Season, Tournament, TournamentResult, User
from app.db.models.enums import SeasonStatus


@dataclass(frozen=True)
class PointsRatingRow:
    player_id: int
    display_name: str
    total_points: Decimal
    tournaments_count: int


@dataclass(frozen=True)
class KnockoutsRatingRow:
    player_id: int
    display_name: str
    knockouts_count: int
    big_knockouts_count: int
    knockout_points: Decimal
    tournaments_count: int

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


class RatingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_points_rating(
        self,
        current_season: bool,
    ) -> list[PointsRatingRow]:
        total_points = func.sum(
            TournamentResult.tournament_points
            + TournamentResult.knockout_points
            + TournamentResult.bonus_points
        )
        statement = (
            select(
                User.id.label("player_id"),
                User.display_name,
                total_points.label("total_points"),
                func.count(TournamentResult.id).label("tournaments_count"),
            )
            .join(TournamentResult, TournamentResult.player_id == User.id)
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .group_by(User.id, User.display_name)
            .having(total_points > 0)
        )
        if current_season:
            statement = statement.join(
                Season,
                Season.id == Tournament.season_id,
            ).where(Season.status == SeasonStatus.ACTIVE)

        result = await self.session.execute(statement.order_by(total_points.desc(), User.id))
        return [
            PointsRatingRow(
                player_id=row.player_id,
                display_name=row.display_name,
                total_points=Decimal(row.total_points),
                tournaments_count=row.tournaments_count,
            )
            for row in result
        ]

    async def get_knockouts_rating(
        self,
        current_season: bool,
    ) -> list[KnockoutsRatingRow]:
        knockouts = func.sum(TournamentResult.knockouts_count)
        big_knockouts = func.sum(TournamentResult.big_knockouts_count)
        knockout_points = func.sum(TournamentResult.knockout_points)
        total_knockouts = knockouts + big_knockouts
        statement = (
            select(
                User.id.label("player_id"),
                User.display_name,
                knockouts.label("knockouts_count"),
                big_knockouts.label("big_knockouts_count"),
                knockout_points.label("knockout_points"),
                func.count(TournamentResult.id).label("tournaments_count"),
            )
            .join(TournamentResult, TournamentResult.player_id == User.id)
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .group_by(User.id, User.display_name)
            .having(total_knockouts > 0)
        )
        if current_season:
            statement = statement.join(
                Season,
                Season.id == Tournament.season_id,
            ).where(Season.status == SeasonStatus.ACTIVE)

        result = await self.session.execute(
            statement.order_by(
                total_knockouts.desc(),
                big_knockouts.desc(),
                User.id,
            )
        )
        return [
            KnockoutsRatingRow(
                player_id=row.player_id,
                display_name=row.display_name,
                knockouts_count=row.knockouts_count,
                big_knockouts_count=row.big_knockouts_count,
                knockout_points=Decimal(row.knockout_points),
                tournaments_count=row.tournaments_count,
            )
            for row in result
        ]
