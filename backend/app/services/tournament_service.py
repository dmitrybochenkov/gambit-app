from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Tournament
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.session import SessionFactory


class TournamentService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_upcoming_schedule(
        self,
        from_date: date | None = None,
    ) -> list[Tournament]:
        async with self.session_factory() as session:
            return await TournamentRepository(session).list_upcoming_active(
                from_date=from_date or date.today()
            )


tournament_service = TournamentService(SessionFactory)
