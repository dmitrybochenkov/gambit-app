from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Player, Season, Tournament, TournamentResult
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
                Player.id.label("player_id"),
                Player.full_name,
                Player.nickname,
                total_points.label("total_points"),
                func.count(TournamentResult.id).label("tournaments_count"),
            )
            .join(TournamentResult, TournamentResult.player_id == Player.id)
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .group_by(Player.id, Player.full_name, Player.nickname)
            .having(total_points > 0)
        )
        if current_season:
            statement = statement.join(
                Season,
                Season.id == Tournament.season_id,
            ).where(Season.status == SeasonStatus.ACTIVE)

        result = await self.session.execute(
            statement.order_by(total_points.desc(), Player.id)
        )
        return [
            PointsRatingRow(
                player_id=row.player_id,
                display_name=self._display_name(row.full_name, row.nickname),
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
        total_knockouts = knockouts + big_knockouts
        statement = (
            select(
                Player.id.label("player_id"),
                Player.full_name,
                Player.nickname,
                knockouts.label("knockouts_count"),
                big_knockouts.label("big_knockouts_count"),
                func.count(TournamentResult.id).label("tournaments_count"),
            )
            .join(TournamentResult, TournamentResult.player_id == Player.id)
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .group_by(Player.id, Player.full_name, Player.nickname)
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
                Player.id,
            )
        )
        return [
            KnockoutsRatingRow(
                player_id=row.player_id,
                display_name=self._display_name(row.full_name, row.nickname),
                knockouts_count=row.knockouts_count,
                big_knockouts_count=row.big_knockouts_count,
                tournaments_count=row.tournaments_count,
            )
            for row in result
        ]

    @staticmethod
    def _display_name(full_name: str | None, nickname: str | None) -> str:
        if full_name and nickname:
            return f"{full_name} ({nickname})"
        return nickname or full_name or ""
