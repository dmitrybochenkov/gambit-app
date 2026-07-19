from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Tournament, TournamentRegistration
from app.db.models.enums import RegistrationStatus, TournamentStatus


class TournamentRegistrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self,
        tournament_id: int,
        player_id: int,
    ) -> TournamentRegistration | None:
        result = await self.session.execute(
            select(TournamentRegistration).where(
                TournamentRegistration.tournament_id == tournament_id,
                TournamentRegistration.player_id == player_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_registered(self, tournament_id: int) -> int:
        result = await self.session.execute(
            select(func.count(TournamentRegistration.id)).where(
                TournamentRegistration.tournament_id == tournament_id,
                TournamentRegistration.status == RegistrationStatus.REGISTERED,
            )
        )
        return result.scalar_one()

    async def list_registered_upcoming(
        self,
        player_id: int,
        from_date: date,
    ) -> list[Tournament]:
        result = await self.session.execute(
            select(Tournament)
            .options(selectinload(Tournament.tournament_type))
            .join(
                TournamentRegistration,
                TournamentRegistration.tournament_id == Tournament.id,
            )
            .where(
                TournamentRegistration.player_id == player_id,
                TournamentRegistration.status == RegistrationStatus.REGISTERED,
                Tournament.status == TournamentStatus.ACTIVE,
                Tournament.date >= from_date,
            )
            .order_by(Tournament.date, Tournament.tournament_type_id)
        )
        return list(result.scalars())
