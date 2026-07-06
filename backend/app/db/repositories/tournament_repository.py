from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tournament
from app.db.models.enums import TournamentStatus


class TournamentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_upcoming_active(
        self,
        from_date: date,
        limit: int = 20,
    ) -> list[Tournament]:
        result = await self.session.execute(
            select(Tournament)
            .where(
                Tournament.status == TournamentStatus.ACTIVE,
                Tournament.date >= from_date,
            )
            .order_by(Tournament.date, Tournament.type)
            .limit(limit)
        )
        return list(result.scalars())

    async def get_by_id(self, tournament_id: int) -> Tournament | None:
        return await self.session.get(Tournament, tournament_id)
