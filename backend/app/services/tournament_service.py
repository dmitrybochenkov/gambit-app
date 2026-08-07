from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import Tournament, TournamentRegistration
from app.db.models.enums import TournamentStatus
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.session import SessionFactory
from app.services.access_policy import ActiveUserRequiredError, access_policy
from app.services.dto import TournamentView


class TournamentRegistrationNotAllowedError(ValueError):
    pass


class TournamentScheduleNotAllowedError(ValueError):
    pass


class TournamentUnavailableError(ValueError):
    pass


class TournamentCancellationUnavailableError(ValueError):
    pass


class TournamentRegistrationAlreadyCheckedInError(ValueError):
    pass


class TournamentService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def get_upcoming_schedule(
        self,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            tournaments = await TournamentRepository(session).list_upcoming_active(
                from_date=from_date or self.clock.today()
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_schedule_for_player(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            try:
                await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentScheduleNotAllowedError from exc
            tournaments = await TournamentRepository(session).list_upcoming_active(
                from_date=from_date or self.clock.today()
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_registration_options_for_player(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            try:
                await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc
            tournaments = await TournamentRepository(session).list_upcoming_active(
                from_date=from_date or self.clock.today()
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_player_upcoming_registrations(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc
            tournaments = await TournamentRegistrationRepository(session).list_registered_upcoming(
                player_id=player.id,
                from_date=from_date or self.clock.today(),
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def register_player_for_tournaments(
        self,
        telegram_id: int,
        tournament_ids: list[int],
        from_date: date | None = None,
    ) -> list[TournamentView]:
        unique_tournament_ids = list(dict.fromkeys(tournament_ids))
        if not unique_tournament_ids:
            return []

        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc

            today = from_date or self.clock.today()
            tournament_repository = TournamentRepository(session)
            registration_repository = TournamentRegistrationRepository(session)
            selected: list[tuple[Tournament, TournamentRegistration | None]] = []

            for tournament_id in unique_tournament_ids:
                tournament = await tournament_repository.get_by_id(tournament_id)
                if (
                    tournament is None
                    or tournament.status != TournamentStatus.ACTIVE
                    or tournament.date < today
                ):
                    raise TournamentUnavailableError

                registration = await registration_repository.get(
                    tournament.id,
                    player.id,
                )
                selected.append((tournament, registration))

            for tournament, registration in selected:
                if registration is None:
                    await registration_repository.add(
                        tournament_id=tournament.id,
                        player_id=player.id,
                    )

            await session.commit()
            return [tournament_view(tournament) for tournament, _ in selected]

    async def cancel_player_tournament_registrations(
        self,
        telegram_id: int,
        tournament_ids: list[int],
        from_date: date | None = None,
    ) -> list[TournamentView]:
        unique_tournament_ids = list(dict.fromkeys(tournament_ids))
        if not unique_tournament_ids:
            return []

        async with self.session_factory() as session:
            try:
                player = await access_policy.require_active_user(session, telegram_id)
            except ActiveUserRequiredError as exc:
                raise TournamentRegistrationNotAllowedError from exc

            today = from_date or self.clock.today()
            tournament_repository = TournamentRepository(session)
            registration_repository = TournamentRegistrationRepository(session)
            tournaments_by_id: dict[int, Tournament] = {}
            for tournament_id in unique_tournament_ids:
                tournament = await tournament_repository.get_by_id(tournament_id)
                if (
                    tournament is None
                    or tournament.status != TournamentStatus.ACTIVE
                    or tournament.date < today
                ):
                    raise TournamentCancellationUnavailableError
                tournaments_by_id[tournament.id] = tournament

                registration = await registration_repository.get(tournament.id, player.id)
                if registration is None:
                    continue
                checked_in = await TournamentResultRepository(
                    session
                ).exists_for_tournament_and_player(
                    tournament.id,
                    player.id,
                )
                if checked_in:
                    raise TournamentRegistrationAlreadyCheckedInError
                await registration_repository.delete(registration)

            await session.commit()
            return [
                tournament_view(tournaments_by_id[tournament_id])
                for tournament_id in unique_tournament_ids
            ]


tournament_service = TournamentService(SessionFactory)


def tournament_view(tournament: Tournament) -> TournamentView:
    return TournamentView(
        id=tournament.id,
        date=tournament.date,
        tournament_type_id=tournament.tournament_type_id,
        tournament_type_name=tournament.tournament_type.name,
    )
