from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.factories import create_user
from app.db.models import Tournament
from app.db.models.enums import (
    TournamentResultSource,
    TournamentStatus,
)
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto import (
    CheckInCandidateView,
    TournamentCheckInView,
    TournamentView,
    UserView,
)
from app.services.player_search import (
    rank_player_candidates,
    validate_display_name,
)
from app.services.tournament_service import tournament_view
from app.services.user_service import (
    IdentityAlreadyExistsError,
    required_user_view,
)


class TournamentCheckInNotFoundError(ValueError):
    pass


class TournamentCheckInClosedError(ValueError):
    pass


class TournamentCheckInUserNotFoundError(ValueError):
    pass


class TournamentCheckInDuplicateNameError(ValueError):
    pass


class TournamentCheckInRegisteredUserError(ValueError):
    pass


@dataclass(frozen=True)
class CheckInResultView:
    tournament: TournamentView
    user: UserView
    created: bool


class TournamentCheckInService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def list_today_tournaments(self, admin_telegram_id: int) -> list[TournamentView]:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournaments = await TournamentRepository(session).list_active_on_date(
                self.clock.today()
            )
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_check_in(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentCheckInView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            return await self._check_in_view(session, tournament.id)

    async def search_registered(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        query: str,
    ) -> list[CheckInCandidateView]:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            players = await self._registered_candidates(session, tournament.id)
            return _score_check_in_players(players, query)

    async def search_users(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        query: str,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            checked_in_ids = await TournamentResultRepository(session).list_checked_in_user_ids(
                tournament.id
            )
            registered_ids = await TournamentRegistrationRepository(
                session
            ).list_registered_user_ids(tournament.id)
            users = await UserRepository(session).list_active_users_for_play()
            candidates = rank_player_candidates(
                [
                    user
                    for user in users
                    if user.id not in checked_in_ids and user.id not in registered_ids
                ],
                query,
                limit=10,
            )
            return [required_user_view(candidate.user) for candidate in candidates]

    async def find_new_player_candidates(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> tuple[str, list[UserView], bool]:
        normalized = validate_display_name(display_name)
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            checked_in_ids = await TournamentResultRepository(session).list_checked_in_user_ids(
                tournament.id
            )
            users = [
                user
                for user in await UserRepository(session).list_active_users_for_play()
                if user.id not in checked_in_ids
            ]
            candidates = rank_player_candidates(users, display_name, limit=10)
            exact_exists = any(
                candidate.user.display_name_normalized == normalized for candidate in candidates
            )
            return (
                normalized,
                [required_user_view(candidate.user) for candidate in candidates],
                exact_exists,
            )

    async def get_user_check_in_confirmation(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> CheckInResultView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            user = await self._get_active_check_in_user(session, user_id)
            return CheckInResultView(tournament_view(tournament), required_user_view(user), False)

    async def get_new_user_check_in_confirmation(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> tuple[TournamentView, str]:
        validate_display_name(display_name)
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            return tournament_view(tournament), display_name

    async def check_in_registered(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> CheckInResultView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            registration_exists = await TournamentRegistrationRepository(session).exists(
                tournament.id,
                user_id,
            )
            if not registration_exists:
                raise TournamentCheckInUserNotFoundError
            user = await self._get_active_check_in_user(session, user_id)
            created = await self._create_result(
                TournamentResultRepository(session),
                tournament_id=tournament.id,
                user_id=user.id,
                source=TournamentResultSource.REGISTERED,
                checked_in_by_user_id=admin.id,
            )
            await session.commit()
            return CheckInResultView(tournament_view(tournament), required_user_view(user), created)

    async def check_in_existing_user(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> CheckInResultView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            user = await self._get_active_check_in_user(session, user_id)
            if await TournamentRegistrationRepository(session).exists(tournament.id, user.id):
                raise TournamentCheckInRegisteredUserError
            created = await self._create_result(
                TournamentResultRepository(session),
                tournament_id=tournament.id,
                user_id=user.id,
                source=TournamentResultSource.WALK_IN_EXISTING,
                checked_in_by_user_id=admin.id,
            )
            await session.commit()
            return CheckInResultView(tournament_view(tournament), required_user_view(user), created)

    async def create_user_and_check_in(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> CheckInResultView:
        normalized = validate_display_name(display_name)
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            existing_names = await UserRepository(session).list_by_display_name_normalized(
                normalized
            )
            if existing_names:
                raise TournamentCheckInDuplicateNameError
            user = create_user(display_name=display_name)
            session.add(user)
            try:
                await session.flush()
                await self._create_result(
                    TournamentResultRepository(session),
                    tournament_id=tournament.id,
                    user_id=user.id,
                    source=TournamentResultSource.WALK_IN_NEW,
                    checked_in_by_user_id=admin.id,
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise IdentityAlreadyExistsError("display_name") from exc
            return CheckInResultView(tournament_view(tournament), required_user_view(user), True)

    async def _require_today_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise TournamentCheckInNotFoundError
        if tournament.status != TournamentStatus.ACTIVE or tournament.date != self.clock.today():
            raise TournamentCheckInClosedError
        return tournament

    async def _get_active_check_in_user(self, session: AsyncSession, user_id: int):
        user = await UserRepository(session).get_active_by_id(user_id)
        if user is None:
            raise TournamentCheckInUserNotFoundError
        return user

    async def _registered_candidates(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> list[CheckInCandidateView]:
        checked_in_ids = await TournamentResultRepository(session).list_checked_in_user_ids(
            tournament_id
        )
        users = await TournamentRegistrationRepository(
            session
        ).list_active_unchecked_registered_users(
            tournament_id,
            checked_in_ids,
        )
        return [
            CheckInCandidateView(
                user_id=user.id,
                display_name=user.display_name,
                is_pre_registered=True,
                is_checked_in=False,
            )
            for user in users
        ]

    async def _create_result(
        self,
        repository: TournamentResultRepository,
        *,
        tournament_id: int,
        user_id: int,
        source: TournamentResultSource,
        checked_in_by_user_id: int,
    ) -> bool:
        existing = await repository.exists_for_tournament_and_player(
            tournament_id,
            user_id,
        )
        if existing:
            return False
        await repository.add_check_in(
            tournament_id=tournament_id,
            user_id=user_id,
            source=source,
            checked_in_at=self.clock.now(),
            checked_in_by_user_id=checked_in_by_user_id,
        )
        return True

    async def _check_in_view(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> TournamentCheckInView:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise TournamentCheckInNotFoundError
        registered_users = await TournamentRegistrationRepository(
            session
        ).list_active_registered_users(tournament_id)
        checked_results = await TournamentResultRepository(session).list_with_users(
            tournament_id,
            order_by_user_id=False,
        )
        checked_by_user_id = {row.user.id: row.result for row in checked_results}
        walk_in_count = sum(
            1 for row in checked_results if row.result.source != TournamentResultSource.REGISTERED
        )
        return TournamentCheckInView(
            tournament=tournament_view(tournament),
            registered_count=len(registered_users),
            checked_in_count=len(checked_results),
            unchecked_registered_count=sum(
                1 for user in registered_users if user.id not in checked_by_user_id
            ),
            walk_in_count=walk_in_count,
        )


def _score_check_in_players(
    players: list[CheckInCandidateView],
    query: str,
) -> list[CheckInCandidateView]:
    candidates = rank_player_candidates(players, query, limit=10)
    return [candidate.user for candidate in candidates]


tournament_check_in_service = TournamentCheckInService(SessionFactory)
