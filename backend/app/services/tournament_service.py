from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Tournament, TournamentRegistration
from app.db.models.enums import PlayerStatus, RegistrationStatus, TournamentStatus
from app.db.repositories.player_repository import PlayerRepository
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.session import SessionFactory


class TournamentRegistrationNotAllowedError(ValueError):
    pass


class TournamentUnavailableError(ValueError):
    pass


class TournamentAlreadyRegisteredError(ValueError):
    pass


class TournamentFullError(ValueError):
    pass


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

    async def register_player(
        self,
        telegram_id: int,
        tournament_id: int,
        from_date: date | None = None,
    ) -> tuple[TournamentRegistration, Tournament]:
        async with self.session_factory() as session:
            player = await PlayerRepository(session).get_by_telegram_id(telegram_id)
            if player is None or player.status != PlayerStatus.ACTIVE:
                raise TournamentRegistrationNotAllowedError

            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            today = from_date or date.today()
            if (
                tournament is None
                or tournament.status != TournamentStatus.ACTIVE
                or tournament.date < today
            ):
                raise TournamentUnavailableError

            repository = TournamentRegistrationRepository(session)
            registration = await repository.get(tournament.id, player.id)
            if registration is not None and registration.status == RegistrationStatus.REGISTERED:
                raise TournamentAlreadyRegisteredError

            if await repository.count_registered(tournament.id) >= tournament.capacity:
                raise TournamentFullError

            now = datetime.now(UTC)
            if registration is None:
                registration = TournamentRegistration(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    status=RegistrationStatus.REGISTERED,
                    registered_at=now,
                )
                session.add(registration)
            else:
                registration.status = RegistrationStatus.REGISTERED
                registration.registered_at = now
                registration.cancelled_at = None

            await session.commit()
            await session.refresh(registration)
            return registration, tournament


tournament_service = TournamentService(SessionFactory)
