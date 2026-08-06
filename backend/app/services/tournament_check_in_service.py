from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.common.clock import Clock, club_clock
from app.db.factories import create_user
from app.db.models import (
    Tournament,
    TournamentRegistration,
    TournamentResult,
    User,
)
from app.db.models.enums import (
    TournamentResultSource,
    TournamentStatus,
    UserRole,
    UserStatus,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
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
    AdminAccessDeniedError,
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
            await self._require_admin(session, admin_telegram_id)
            result = await session.execute(
                select(Tournament)
                .options(selectinload(Tournament.tournament_type))
                .where(
                    Tournament.status == TournamentStatus.ACTIVE,
                    Tournament.date == self.clock.today(),
                )
                .order_by(Tournament.date, Tournament.tournament_type_id)
            )
            return [tournament_view(tournament) for tournament in result.scalars()]

    async def get_check_in(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentCheckInView:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            return await self._check_in_view(session, tournament.id)

    async def search_registered(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        query: str,
    ) -> list[CheckInCandidateView]:
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
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
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            checked_in_ids = await self._checked_in_user_ids(session, tournament.id)
            registered_ids = await self._registered_user_ids(session, tournament.id)
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
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            checked_in_ids = await self._checked_in_user_ids(session, tournament.id)
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
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            user = await self._require_active_user(session, user_id)
            return CheckInResultView(tournament_view(tournament), required_user_view(user), False)

    async def get_new_user_check_in_confirmation(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> tuple[TournamentView, str]:
        validate_display_name(display_name)
        async with self.session_factory() as session:
            await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            return tournament_view(tournament), display_name

    async def check_in_registered(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> CheckInResultView:
        async with self.session_factory() as session:
            admin = await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            registration = await session.scalar(
                select(TournamentRegistration.id).where(
                    TournamentRegistration.tournament_id == tournament.id,
                    TournamentRegistration.player_id == user_id,
                )
            )
            if registration is None:
                raise TournamentCheckInUserNotFoundError
            user = await self._require_active_user(session, user_id)
            created = await self._create_result(
                session,
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
            admin = await self._require_admin(session, admin_telegram_id)
            tournament = await self._require_today_tournament(session, tournament_id)
            user = await self._require_active_user(session, user_id)
            registration = await session.scalar(
                select(TournamentRegistration.id).where(
                    TournamentRegistration.tournament_id == tournament.id,
                    TournamentRegistration.player_id == user.id,
                )
            )
            if registration is not None:
                raise TournamentCheckInRegisteredUserError
            created = await self._create_result(
                session,
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
            admin = await self._require_admin(session, admin_telegram_id)
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
                    session,
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

    async def _require_admin(self, session: AsyncSession, telegram_id: int):
        admin = await UserRepository(session).get_by_telegram_id(telegram_id)
        if (
            admin is None
            or admin.status != UserStatus.ACTIVE
            or admin.role not in {UserRole.ADMIN, UserRole.SUPERADMIN}
        ):
            raise AdminAccessDeniedError
        return admin

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

    async def _require_active_user(self, session: AsyncSession, user_id: int):
        user = await UserRepository(session).get_by_id(user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise TournamentCheckInUserNotFoundError
        return user

    async def _registered_candidates(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> list[CheckInCandidateView]:
        checked_in_ids = await self._checked_in_user_ids(session, tournament_id)
        result = await session.execute(
            select(User)
            .join(TournamentRegistration, TournamentRegistration.player_id == User.id)
            .where(
                TournamentRegistration.tournament_id == tournament_id,
                User.status == UserStatus.ACTIVE,
                User.id.not_in(checked_in_ids),
            )
            .order_by(User.display_name, User.id)
        )
        return [
            CheckInCandidateView(
                user_id=user.id,
                display_name=user.display_name,
                is_pre_registered=True,
                is_checked_in=False,
            )
            for user in result.scalars()
        ]

    async def _checked_in_user_ids(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> set[int]:
        result = await session.execute(
            select(TournamentResult.player_id).where(
                TournamentResult.tournament_id == tournament_id
            )
        )
        return set(result.scalars())

    async def _registered_user_ids(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> set[int]:
        result = await session.execute(
            select(TournamentRegistration.player_id).where(
                TournamentRegistration.tournament_id == tournament_id
            )
        )
        return set(result.scalars())

    async def _create_result(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        user_id: int,
        source: TournamentResultSource,
        checked_in_by_user_id: int,
    ) -> bool:
        existing = await session.scalar(
            select(TournamentResult.id).where(
                TournamentResult.tournament_id == tournament_id,
                TournamentResult.player_id == user_id,
            )
        )
        if existing is not None:
            return False
        session.add(
            TournamentResult(
                tournament_id=tournament_id,
                player_id=user_id,
                source=source,
                checked_in_at=self.clock.now(),
                checked_in_by_user_id=checked_in_by_user_id,
                place=None,
                knockouts_count=0,
                big_knockouts_count=0,
                bonus_points=0,
                tournament_points=0,
                knockout_points=0,
            )
        )
        await session.flush()
        return True

    async def _check_in_view(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> TournamentCheckInView:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise TournamentCheckInNotFoundError
        registered_result = await session.execute(
            select(User)
            .join(TournamentRegistration, TournamentRegistration.player_id == User.id)
            .where(
                TournamentRegistration.tournament_id == tournament_id,
                User.status == UserStatus.ACTIVE,
            )
            .order_by(User.display_name, User.id)
        )
        registered_users = list(registered_result.scalars())
        result_rows = await session.execute(
            select(TournamentResult, User)
            .join(User, User.id == TournamentResult.player_id)
            .where(TournamentResult.tournament_id == tournament_id)
            .order_by(User.display_name, User.id)
        )
        checked_results = list(result_rows.all())
        checked_by_user_id = {user.id: result for result, user in checked_results}
        walk_in_count = sum(
            1 for result, _ in checked_results if result.source != TournamentResultSource.REGISTERED
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
