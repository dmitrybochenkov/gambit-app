from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TournamentResult, User
from app.db.models.enums import TournamentResultSource


@dataclass(frozen=True)
class TournamentResultUserRecord:
    result: TournamentResult
    user: User


class TournamentResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_tournament_and_player(
        self,
        tournament_id: int,
        player_id: int,
    ) -> TournamentResult | None:
        result = await self.session.execute(
            select(TournamentResult).where(
                TournamentResult.tournament_id == tournament_id,
                TournamentResult.player_id == player_id,
            )
        )
        return result.scalar_one_or_none()

    async def exists_for_tournament_and_player(
        self,
        tournament_id: int,
        player_id: int,
    ) -> bool:
        result = await self.session.execute(
            select(TournamentResult.id).where(
                TournamentResult.tournament_id == tournament_id,
                TournamentResult.player_id == player_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_by_tournament(self, tournament_id: int) -> list[TournamentResult]:
        result = await self.session.execute(
            select(TournamentResult).where(TournamentResult.tournament_id == tournament_id)
        )
        return list(result.scalars())

    async def list_with_users(
        self,
        tournament_id: int,
        *,
        order_by_user_id: bool = False,
    ) -> list[TournamentResultUserRecord]:
        statement = (
            select(TournamentResult, User)
            .join(User, User.id == TournamentResult.player_id)
            .where(TournamentResult.tournament_id == tournament_id)
        )
        if order_by_user_id:
            statement = statement.order_by(User.id)
        else:
            statement = statement.order_by(User.display_name, User.id)
        result = await self.session.execute(statement)
        return [TournamentResultUserRecord(result=item, user=user) for item, user in result.all()]

    async def list_by_tournament_and_place(
        self,
        tournament_id: int,
        place: int,
        *,
        exclude_result_id: int | None = None,
    ) -> list[TournamentResult]:
        statement = select(TournamentResult).where(
            TournamentResult.tournament_id == tournament_id,
            TournamentResult.place == place,
        )
        if exclude_result_id is not None:
            statement = statement.where(TournamentResult.id != exclude_result_id)
        result = await self.session.execute(statement)
        return list(result.scalars())

    async def list_checked_in_user_ids(self, tournament_id: int) -> set[int]:
        result = await self.session.execute(
            select(TournamentResult.player_id).where(
                TournamentResult.tournament_id == tournament_id
            )
        )
        return set(result.scalars())

    async def add_check_in(
        self,
        *,
        tournament_id: int,
        user_id: int,
        source: TournamentResultSource,
        checked_in_at: datetime,
        checked_in_by_user_id: int,
    ) -> TournamentResult:
        result = TournamentResult(
            tournament_id=tournament_id,
            player_id=user_id,
            source=source,
            checked_in_at=checked_in_at,
            checked_in_by_user_id=checked_in_by_user_id,
            place=None,
            knockouts_count=0,
            big_knockouts_count=0,
            bonus_points=0,
            tournament_points=0,
            knockout_points=0,
        )
        self.session.add(result)
        await self.session.flush()
        return result
