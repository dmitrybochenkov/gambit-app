from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tournament, TournamentResult, User
from app.db.repositories.hall_of_fame_repository import HallOfFameRepository
from app.db.repositories.result_scopes import closed_tournament_filter


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
    knockout_tournaments_count: int

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


@dataclass(frozen=True)
class RatingHonours:
    season_champion_titles_by_player_id: dict[int, int]
    season_knockout_leader_titles_by_player_id: dict[int, int]


class RatingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_points_rating(
        self,
        season_id: int | None = None,
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
            .where(closed_tournament_filter())
            .group_by(User.id, User.display_name)
            .having(total_points > 0)
        )
        if season_id is not None:
            statement = statement.where(Tournament.season_id == season_id)

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
        season_id: int | None = None,
    ) -> list[KnockoutsRatingRow]:
        knockouts = func.sum(TournamentResult.knockouts_count)
        big_knockouts = func.sum(TournamentResult.big_knockouts_count)
        total_knockouts = knockouts + big_knockouts
        knockout_tournament_ids = (
            select(TournamentResult.tournament_id)
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .where(closed_tournament_filter())
            .group_by(TournamentResult.tournament_id)
            .having(
                func.sum(TournamentResult.knockouts_count + TournamentResult.big_knockouts_count)
                > 0
            )
        )
        if season_id is not None:
            knockout_tournament_ids = knockout_tournament_ids.where(
                Tournament.season_id == season_id
            )
        statement = (
            select(
                User.id.label("player_id"),
                User.display_name,
                knockouts.label("knockouts_count"),
                big_knockouts.label("big_knockouts_count"),
                func.count(TournamentResult.id)
                .filter(TournamentResult.tournament_id.in_(knockout_tournament_ids))
                .label("knockout_tournaments_count"),
            )
            .join(TournamentResult, TournamentResult.player_id == User.id)
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .where(closed_tournament_filter())
            .group_by(User.id, User.display_name)
            .having(total_knockouts > 0)
        )
        if season_id is not None:
            statement = statement.where(Tournament.season_id == season_id)

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
                knockout_tournaments_count=row.knockout_tournaments_count,
            )
            for row in result
        ]

    async def get_rating_honours(self, today: date) -> RatingHonours:
        rows = await HallOfFameRepository(self.session).list_completed_entries(today)
        champion_counts: dict[int, int] = {}
        knockout_counts: dict[int, int] = {}
        for row in rows:
            if row.champion_player_id is not None:
                champion_counts[row.champion_player_id] = (
                    champion_counts.get(row.champion_player_id, 0) + 1
                )
            if row.knockout_leader_player_id is not None:
                knockout_counts[row.knockout_leader_player_id] = (
                    knockout_counts.get(row.knockout_leader_player_id, 0) + 1
                )
        return RatingHonours(
            season_champion_titles_by_player_id=champion_counts,
            season_knockout_leader_titles_by_player_id=knockout_counts,
        )
