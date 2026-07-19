from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Tournament, TournamentRegistration
from app.db.models.enums import (
    PlayerRole,
    PlayerStatus,
    RegistrationStatus,
    TournamentStatus,
)
from app.db.repositories.player_repository import PlayerRepository
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.session import SessionFactory
from app.services.dto import PlayerView, TournamentView
from app.services.player_service import AdminAccessDeniedError, required_player_view


class TournamentRegistrationNotAllowedError(ValueError):
    pass


class TournamentScheduleNotAllowedError(ValueError):
    pass


class TournamentUnavailableError(ValueError):
    pass


class TournamentPlayerNotFoundError(ValueError):
    pass


class TournamentCancellationUnavailableError(ValueError):
    pass


class TournamentService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_upcoming_schedule(
        self,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            tournaments = await TournamentRepository(session).list_upcoming_active(
                from_date=from_date or date.today()
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_schedule_for_player(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            player = await PlayerRepository(session).get_by_telegram_id(telegram_id)
            if player is None or player.status != PlayerStatus.ACTIVE:
                raise TournamentScheduleNotAllowedError
            tournaments = await TournamentRepository(session).list_upcoming_active(
                from_date=from_date or date.today()
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_registration_options_for_player(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            player = await PlayerRepository(session).get_by_telegram_id(telegram_id)
            if player is None or player.status != PlayerStatus.ACTIVE:
                raise TournamentRegistrationNotAllowedError
            tournaments = await TournamentRepository(session).list_upcoming_active(
                from_date=from_date or date.today()
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_player_upcoming_registrations(
        self,
        telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            player = await PlayerRepository(session).get_by_telegram_id(telegram_id)
            if player is None or player.status != PlayerStatus.ACTIVE:
                raise TournamentRegistrationNotAllowedError
            tournaments = await TournamentRegistrationRepository(
                session
            ).list_registered_upcoming(
                player_id=player.id,
                from_date=from_date or date.today(),
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def list_registration_tournaments_for_admin(
        self,
        admin_telegram_id: int,
        from_date: date | None = None,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournaments = await TournamentRepository(session).list_upcoming_active(
                from_date=from_date or date.today()
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def list_players_for_admin_registration(
        self,
        admin_telegram_id: int,
    ) -> list[PlayerView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            players = await PlayerRepository(session).list_active_players()
            return [required_player_view(player) for player in players]

    async def register_player_for_tournament_by_admin(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
        from_date: date | None = None,
    ) -> tuple[TournamentView, PlayerView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            today = from_date or date.today()
            tournament = await TournamentRepository(session).get_by_id(tournament_id)
            if (
                tournament is None
                or tournament.status != TournamentStatus.ACTIVE
                or tournament.date < today
            ):
                raise TournamentUnavailableError

            player = await PlayerRepository(session).get_by_id(player_id)
            if (
                player is None
                or player.status != PlayerStatus.ACTIVE
                or player.telegram_id <= 0
            ):
                raise TournamentPlayerNotFoundError

            repository = TournamentRegistrationRepository(session)
            registration = await repository.get(tournament.id, player.id)
            now = datetime.now(UTC)
            if registration is None:
                session.add(
                    TournamentRegistration(
                        tournament_id=tournament.id,
                        player_id=player.id,
                        status=RegistrationStatus.REGISTERED,
                        registered_at=now,
                    )
                )
            elif registration.status != RegistrationStatus.REGISTERED:
                registration.status = RegistrationStatus.REGISTERED
                registration.registered_at = now
                registration.cancelled_at = None

            await session.commit()
            return tournament_view(tournament), required_player_view(player)

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
            player = await PlayerRepository(session).get_by_telegram_id(telegram_id)
            if player is None or player.status != PlayerStatus.ACTIVE:
                raise TournamentRegistrationNotAllowedError

            today = from_date or date.today()
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

            now = datetime.now(UTC)
            for tournament, registration in selected:
                if registration is None:
                    session.add(
                        TournamentRegistration(
                            tournament_id=tournament.id,
                            player_id=player.id,
                            status=RegistrationStatus.REGISTERED,
                            registered_at=now,
                        )
                    )
                elif registration.status != RegistrationStatus.REGISTERED:
                    registration.status = RegistrationStatus.REGISTERED
                    registration.registered_at = now
                    registration.cancelled_at = None

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
            player = await PlayerRepository(session).get_by_telegram_id(telegram_id)
            if player is None or player.status != PlayerStatus.ACTIVE:
                raise TournamentRegistrationNotAllowedError

            repository = TournamentRegistrationRepository(session)
            available_tournaments = await repository.list_registered_upcoming(
                player_id=player.id,
                from_date=from_date or date.today(),
            )
            tournaments_by_id = {
                tournament.id: tournament
                for tournament in available_tournaments
            }
            if any(
                tournament_id not in tournaments_by_id
                for tournament_id in unique_tournament_ids
            ):
                raise TournamentCancellationUnavailableError

            registrations: list[TournamentRegistration] = []
            for tournament_id in unique_tournament_ids:
                registration = await repository.get(tournament_id, player.id)
                if (
                    registration is None
                    or registration.status != RegistrationStatus.REGISTERED
                ):
                    raise TournamentCancellationUnavailableError
                registrations.append(registration)

            now = datetime.now(UTC)
            for registration in registrations:
                registration.status = RegistrationStatus.CANCELLED
                registration.cancelled_at = now

            await session.commit()
            return [
                tournament_view(tournaments_by_id[tournament_id])
                for tournament_id in unique_tournament_ids
            ]

    @staticmethod
    async def _require_admin(
        session: AsyncSession,
        telegram_id: int,
    ) -> None:
        admin = await PlayerRepository(session).get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != PlayerStatus.ACTIVE
            or admin.role not in {PlayerRole.ADMIN, PlayerRole.SUPERADMIN}
        ):
            raise AdminAccessDeniedError


tournament_service = TournamentService(SessionFactory)


def tournament_view(tournament: Tournament) -> TournamentView:
    tournament_type = tournament.__dict__.get("tournament_type")
    return TournamentView(
        id=tournament.id,
        date=tournament.date,
        tournament_type_id=tournament.tournament_type_id,
        tournament_type_name=tournament_type.name if tournament_type is not None else None,
    )
