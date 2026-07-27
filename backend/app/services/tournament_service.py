from datetime import UTC, date, datetime
from difflib import SequenceMatcher

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.normalization import normalize_display_name
from app.db.models import Tournament, TournamentRegistration
from app.db.models.enums import (
    RegistrationStatus,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.dto import TournamentView, UserView
from app.services.user_service import (
    AdminAccessDeniedError,
    required_user_view,
)


class TournamentRegistrationNotAllowedError(ValueError):
    pass


class TournamentScheduleNotAllowedError(ValueError):
    pass


class TournamentUnavailableError(ValueError):
    pass


class TournamentUserNotFoundError(ValueError):
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
            player = await UserRepository(session).get_by_telegram_id(telegram_id)
            if (
                player is None
                or player.status != UserStatus.ACTIVE
                or player.role != UserRole.PLAYER
            ):
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
            player = await UserRepository(session).get_by_telegram_id(telegram_id)
            if (
                player is None
                or player.status != UserStatus.ACTIVE
                or player.role != UserRole.PLAYER
            ):
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
            player = await UserRepository(session).get_by_telegram_id(telegram_id)
            if (
                player is None
                or player.status != UserStatus.ACTIVE
                or player.role != UserRole.PLAYER
            ):
                raise TournamentRegistrationNotAllowedError
            tournaments = await TournamentRegistrationRepository(session).list_registered_upcoming(
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
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            players = await UserRepository(session).list_active_players()
            return _sort_players_by_display_name([required_user_view(player) for player in players])

    async def search_players_for_admin_registration(
        self,
        admin_telegram_id: int,
        query: str,
        limit: int = 10,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            players = await UserRepository(session).list_active_players()
            scored_players = [
                (score, required_user_view(player))
                for player in players
                if (score := _player_search_score(player, query)) > 0
            ]
            scored_players.sort(
                key=lambda item: (-item[0], item[1].display_name.casefold(), item[1].id)
            )
            return [player for _, player in scored_players[:limit]]

    async def register_player_for_tournament_by_admin(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
        from_date: date | None = None,
    ) -> tuple[TournamentView, UserView]:
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

            player = await UserRepository(session).get_by_id(player_id)
            if (
                player is None
                or player.status != UserStatus.ACTIVE
                or player.role != UserRole.PLAYER
            ):
                raise TournamentUserNotFoundError

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
            return tournament_view(tournament), required_user_view(player)

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
            player = await UserRepository(session).get_by_telegram_id(telegram_id)
            if (
                player is None
                or player.status != UserStatus.ACTIVE
                or player.role != UserRole.PLAYER
            ):
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
            player = await UserRepository(session).get_by_telegram_id(telegram_id)
            if (
                player is None
                or player.status != UserStatus.ACTIVE
                or player.role != UserRole.PLAYER
            ):
                raise TournamentRegistrationNotAllowedError

            repository = TournamentRegistrationRepository(session)
            available_tournaments = await repository.list_registered_upcoming(
                player_id=player.id,
                from_date=from_date or date.today(),
            )
            tournaments_by_id = {tournament.id: tournament for tournament in available_tournaments}
            if any(
                tournament_id not in tournaments_by_id for tournament_id in unique_tournament_ids
            ):
                raise TournamentCancellationUnavailableError

            registrations: list[TournamentRegistration] = []
            for tournament_id in unique_tournament_ids:
                registration = await repository.get(tournament_id, player.id)
                if registration is None or registration.status != RegistrationStatus.REGISTERED:
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
        admin = await UserRepository(session).get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != UserStatus.ACTIVE
            or admin.role not in {UserRole.ADMIN, UserRole.SUPERADMIN}
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


def _sort_players_by_display_name(players: list[UserView]) -> list[UserView]:
    return sorted(
        players,
        key=lambda player: (player.display_name.casefold(), player.id),
    )


def _player_search_score(player: object, query: str) -> int:
    normalized_query = normalize_display_name(query)
    if not normalized_query:
        return 0

    display_name = getattr(player, "display_name", None)
    display_name_normalized = getattr(player, "display_name_normalized", None)
    candidate = display_name_normalized or normalize_display_name(display_name)
    if not candidate:
        return 0

    if normalized_query == candidate:
        return 300
    if normalized_query in candidate:
        return 200 + len(normalized_query)
    ratio = SequenceMatcher(None, normalized_query, candidate).ratio()
    if ratio >= 0.55:
        return int(ratio * 100)
    return 0
