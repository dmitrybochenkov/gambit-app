from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Season, Tournament, TournamentResult, User
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


@dataclass(frozen=True)
class HallOfFameSeasonRow:
    season_id: int
    season_name: str
    starts_at: date
    champion_player_id: int | None
    champion_display_name: str | None
    knockout_leader_player_id: int | None
    knockout_leader_display_name: str | None


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
        return RatingHonours(
            season_champion_titles_by_player_id=await self._get_completed_season_champion_titles(
                today
            ),
            season_knockout_leader_titles_by_player_id=(
                await self._get_completed_season_knockout_leader_titles(today)
            ),
        )

    async def list_hall_of_fame_seasons(self) -> list[HallOfFameSeasonRow]:
        season_rows = await self._list_completed_seasons_with_results()
        champions = await self._get_hall_of_fame_champions()
        knockout_leaders = await self._get_hall_of_fame_knockout_leaders()
        return [
            HallOfFameSeasonRow(
                season_id=row.season_id,
                season_name=row.season_name,
                starts_at=row.starts_at,
                champion_player_id=champions.get(row.season_id, (None, None))[0],
                champion_display_name=champions.get(row.season_id, (None, None))[1],
                knockout_leader_player_id=knockout_leaders.get(row.season_id, (None, None))[0],
                knockout_leader_display_name=knockout_leaders.get(row.season_id, (None, None))[1],
            )
            for row in season_rows
        ]

    async def _list_completed_seasons_with_results(self) -> list[object]:
        result = await self.session.execute(
            select(
                Season.id.label("season_id"),
                Season.name.label("season_name"),
                Season.starts_at,
            )
            .join(Tournament, Tournament.season_id == Season.id)
            .join(TournamentResult, TournamentResult.tournament_id == Tournament.id)
            .where(Season.ends_at.is_not(None), closed_tournament_filter())
            .group_by(Season.id, Season.name, Season.starts_at)
            .order_by(Season.starts_at.desc(), Season.id.desc())
        )
        return list(result)

    async def _get_hall_of_fame_champions(self) -> dict[int, tuple[int, str]]:
        total_points = func.sum(
            TournamentResult.tournament_points
            + TournamentResult.knockout_points
            + TournamentResult.bonus_points
        ).label("total_points")
        ranked = (
            select(
                Tournament.season_id.label("season_id"),
                TournamentResult.player_id.label("player_id"),
                func.row_number()
                .over(
                    partition_by=Tournament.season_id,
                    order_by=(desc(total_points), TournamentResult.player_id),
                )
                .label("rank"),
            )
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .join(Season, Season.id == Tournament.season_id)
            .where(Season.ends_at.is_not(None), closed_tournament_filter())
            .group_by(Tournament.season_id, TournamentResult.player_id)
            .having(total_points > 0)
            .subquery()
        )
        result = await self.session.execute(
            select(ranked.c.season_id, User.id, User.display_name)
            .join(User, User.id == ranked.c.player_id)
            .where(ranked.c.rank == 1)
        )
        return {int(row.season_id): (int(row.id), row.display_name) for row in result}

    async def _get_hall_of_fame_knockout_leaders(self) -> dict[int, tuple[int, str]]:
        knockouts = func.sum(TournamentResult.knockouts_count).label("knockouts")
        big_knockouts = func.sum(TournamentResult.big_knockouts_count).label("big_knockouts")
        total_knockouts = (knockouts + big_knockouts).label("total_knockouts")
        ranked = (
            select(
                Tournament.season_id.label("season_id"),
                TournamentResult.player_id.label("player_id"),
                func.row_number()
                .over(
                    partition_by=Tournament.season_id,
                    order_by=(
                        desc(total_knockouts),
                        desc(big_knockouts),
                        TournamentResult.player_id,
                    ),
                )
                .label("rank"),
            )
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .join(Season, Season.id == Tournament.season_id)
            .where(Season.ends_at.is_not(None), closed_tournament_filter())
            .group_by(Tournament.season_id, TournamentResult.player_id)
            .having(total_knockouts > 0)
            .subquery()
        )
        result = await self.session.execute(
            select(ranked.c.season_id, User.id, User.display_name)
            .join(User, User.id == ranked.c.player_id)
            .where(ranked.c.rank == 1)
        )
        return {int(row.season_id): (int(row.id), row.display_name) for row in result}

    async def _get_completed_season_champion_titles(self, today: date) -> dict[int, int]:
        total_points = func.sum(
            TournamentResult.tournament_points
            + TournamentResult.knockout_points
            + TournamentResult.bonus_points
        ).label("total_points")
        ranked = (
            select(
                Tournament.season_id.label("season_id"),
                TournamentResult.player_id.label("player_id"),
                func.row_number()
                .over(
                    partition_by=Tournament.season_id,
                    order_by=(desc(total_points), TournamentResult.player_id),
                )
                .label("rank"),
            )
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .join(Season, Season.id == Tournament.season_id)
            .where(
                Season.ends_at.is_not(None),
                Season.ends_at < today,
                closed_tournament_filter(),
            )
            .group_by(Tournament.season_id, TournamentResult.player_id)
            .having(total_points > 0)
            .subquery()
        )
        result = await self.session.execute(select(ranked.c.player_id).where(ranked.c.rank == 1))
        return dict(Counter(int(player_id) for player_id in result.scalars()))

    async def _get_completed_season_knockout_leader_titles(
        self,
        today: date,
    ) -> dict[int, int]:
        knockouts = func.sum(TournamentResult.knockouts_count).label("knockouts")
        big_knockouts = func.sum(TournamentResult.big_knockouts_count).label("big_knockouts")
        total_knockouts = (knockouts + big_knockouts).label("total_knockouts")
        ranked = (
            select(
                Tournament.season_id.label("season_id"),
                TournamentResult.player_id.label("player_id"),
                func.row_number()
                .over(
                    partition_by=Tournament.season_id,
                    order_by=(
                        desc(total_knockouts),
                        desc(big_knockouts),
                        TournamentResult.player_id,
                    ),
                )
                .label("rank"),
            )
            .join(Tournament, Tournament.id == TournamentResult.tournament_id)
            .join(Season, Season.id == Tournament.season_id)
            .where(
                Season.ends_at.is_not(None),
                Season.ends_at < today,
                closed_tournament_filter(),
            )
            .group_by(Tournament.season_id, TournamentResult.player_id)
            .having(total_knockouts > 0)
            .subquery()
        )
        result = await self.session.execute(select(ranked.c.player_id).where(ranked.c.rank == 1))
        return dict(Counter(int(player_id) for player_id in result.scalars()))
