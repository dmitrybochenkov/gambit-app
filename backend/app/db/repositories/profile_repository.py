from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Player, Season, Tournament, TournamentResult
from app.db.models.enums import SeasonStatus


@dataclass(frozen=True)
class PlayerProfileStats:
    display_name: str
    total_points: Decimal
    knockout_points: Decimal
    knockouts_count: int
    big_knockouts_count: int
    tournaments_count: int
    first_places_count: int
    second_places_count: int
    third_places_count: int
    fourth_places_count: int
    fifth_places_count: int

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_player_stats(
        self,
        telegram_id: int,
        current_season: bool,
    ) -> PlayerProfileStats | None:
        total_points = func.coalesce(
            func.sum(
                TournamentResult.tournament_points
                + TournamentResult.knockout_points
                + TournamentResult.bonus_points
            ),
            0,
        )
        knockouts = func.coalesce(func.sum(TournamentResult.knockouts_count), 0)
        big_knockouts = func.coalesce(
            func.sum(TournamentResult.big_knockouts_count),
            0,
        )
        knockout_points = func.coalesce(func.sum(TournamentResult.knockout_points), 0)

        statement = (
            select(
                Player.display_name,
                total_points.label("total_points"),
                knockout_points.label("knockout_points"),
                func.count(TournamentResult.id).label("tournaments_count"),
                knockouts.label("knockouts_count"),
                big_knockouts.label("big_knockouts_count"),
                self._place_count(1).label("first_places_count"),
                self._place_count(2).label("second_places_count"),
                self._place_count(3).label("third_places_count"),
                self._place_count(4).label("fourth_places_count"),
                self._place_count(5).label("fifth_places_count"),
            )
            .select_from(Player)
            .join(TournamentResult, TournamentResult.player_id == Player.id)
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .where(Player.telegram_id == telegram_id)
            .group_by(Player.id, Player.display_name)
        )
        if current_season:
            statement = statement.join(
                Season,
                Season.id == Tournament.season_id,
            ).where(Season.status == SeasonStatus.ACTIVE)

        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            player = await self.session.scalar(
                select(Player).where(Player.telegram_id == telegram_id)
            )
            if player is None:
                return None
            return PlayerProfileStats(
                display_name=player.display_name,
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

        return PlayerProfileStats(
            display_name=row.display_name,
            total_points=Decimal(row.total_points),
            knockout_points=Decimal(row.knockout_points),
            tournaments_count=row.tournaments_count,
            knockouts_count=row.knockouts_count,
            big_knockouts_count=row.big_knockouts_count,
            first_places_count=row.first_places_count,
            second_places_count=row.second_places_count,
            third_places_count=row.third_places_count,
            fourth_places_count=row.fourth_places_count,
            fifth_places_count=row.fifth_places_count,
        )

    @staticmethod
    def _place_count(place: int) -> object:
        return func.coalesce(
            func.sum(case((TournamentResult.place == place, 1), else_=0)),
            0,
        )
