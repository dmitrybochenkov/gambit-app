from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tournament, TournamentResult, User
from app.db.repositories.result_scopes import closed_tournament_filter


@dataclass(frozen=True)
class PlayerProfileStats:
    display_name: str
    total_points: Decimal
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
        player_id: int,
        season_id: int | None = None,
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
        statement = (
            select(
                User.display_name,
                total_points.label("total_points"),
                func.count(TournamentResult.id).label("tournaments_count"),
                knockouts.label("knockouts_count"),
                big_knockouts.label("big_knockouts_count"),
                self._place_count(1).label("first_places_count"),
                self._place_count(2).label("second_places_count"),
                self._place_count(3).label("third_places_count"),
                self._place_count(4).label("fourth_places_count"),
                self._place_count(5).label("fifth_places_count"),
            )
            .select_from(User)
            .join(TournamentResult, TournamentResult.player_id == User.id)
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .where(User.id == player_id, closed_tournament_filter())
            .group_by(User.id, User.display_name)
        )
        if season_id is not None:
            statement = statement.where(Tournament.season_id == season_id)

        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            player = await self.session.get(User, player_id)
            if player is None:
                return None
            return PlayerProfileStats(
                display_name=player.display_name,
                total_points=Decimal("0"),
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
