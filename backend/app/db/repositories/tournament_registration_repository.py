from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TournamentRegistration
from app.db.models.enums import RegistrationStatus


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
