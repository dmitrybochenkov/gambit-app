from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TournamentCombination, TournamentResult, User
from app.db.models.enums import TournamentCombinationType


@dataclass(frozen=True)
class TournamentCombinationUserRecord:
    combination: TournamentCombination
    user: User


class TournamentCombinationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_with_users(self, tournament_id: int) -> list[TournamentCombinationUserRecord]:
        result = await self.session.execute(
            select(TournamentCombination, User)
            .join(User, User.id == TournamentCombination.player_id)
            .where(TournamentCombination.tournament_id == tournament_id)
            .order_by(User.display_name_normalized, User.id, TournamentCombination.id)
        )
        return [
            TournamentCombinationUserRecord(combination=combination, user=user)
            for combination, user in result.all()
        ]

    async def list_player_candidates(self, tournament_id: int) -> list[User]:
        result = await self.session.execute(
            select(User)
            .join(TournamentResult, TournamentResult.player_id == User.id)
            .where(TournamentResult.tournament_id == tournament_id)
            .order_by(User.display_name_normalized, User.id)
        )
        return list(result.scalars())

    async def add(
        self,
        *,
        tournament_id: int,
        player_id: int,
        combination_type: TournamentCombinationType,
    ) -> TournamentCombination:
        combination = TournamentCombination(
            tournament_id=tournament_id,
            player_id=player_id,
            combination_type=combination_type,
        )
        self.session.add(combination)
        await self.session.flush()
        return combination

    async def delete_by_id(self, *, tournament_id: int, combination_id: int) -> bool:
        result = await self.session.execute(
            delete(TournamentCombination).where(
                TournamentCombination.id == combination_id,
                TournamentCombination.tournament_id == tournament_id,
            )
        )
        return bool(result.rowcount)
