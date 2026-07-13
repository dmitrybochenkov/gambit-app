from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Tournament, WeeklyTournamentTemplate
from app.db.models.enums import TournamentStatus, TournamentTypeStatus


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
            .options(selectinload(Tournament.tournament_type))
            .where(
                Tournament.status == TournamentStatus.ACTIVE,
                Tournament.date >= from_date,
            )
            .order_by(Tournament.date, Tournament.tournament_type_id)
            .limit(limit)
        )
        return list(result.scalars())

    async def get_by_id(self, tournament_id: int) -> Tournament | None:
        result = await self.session.execute(
            select(Tournament)
            .options(selectinload(Tournament.tournament_type))
            .where(Tournament.id == tournament_id)
        )
        return result.scalar_one_or_none()

    async def exists_for_date_and_type_id(
        self,
        tournament_date: date,
        tournament_type_id: int,
    ) -> bool:
        result = await self.session.execute(
            select(Tournament.id).where(
                Tournament.date == tournament_date,
                Tournament.tournament_type_id == tournament_type_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_active_weekly_templates(self) -> list[WeeklyTournamentTemplate]:
        result = await self.session.execute(
            select(WeeklyTournamentTemplate)
            .where(WeeklyTournamentTemplate.is_active.is_(True))
            .join(WeeklyTournamentTemplate.tournament_type)
            .where(WeeklyTournamentTemplate.tournament_type.has(status=TournamentTypeStatus.ACTIVE))
            .options(selectinload(WeeklyTournamentTemplate.tournament_type))
            .order_by(
                WeeklyTournamentTemplate.weekday,
                WeeklyTournamentTemplate.rotation_order,
                WeeklyTournamentTemplate.id,
            )
        )
        return list(result.scalars())
