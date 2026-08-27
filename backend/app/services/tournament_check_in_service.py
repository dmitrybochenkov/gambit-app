from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.factories import create_user
from app.db.models import Tournament
from app.db.models.enums import TournamentResultSource, UserRole
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.domain.open_tournament_edit_policy import (
    can_edit_open_tournament_for_actor,
    is_superadmin_late_open_tournament_override,
)
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.check_in import (
    CheckedInPlayersView,
    CheckedInPlayerView,
    CheckInCandidateView,
    TournamentCheckInView,
)
from app.services.dto.rewards import PlayerRewardView
from app.services.dto.tournaments import TournamentView
from app.services.dto.users import UserView
from app.services.player_reward_service import PlayerRewardService
from app.services.player_search import (
    rank_player_candidates,
    validate_display_name,
)
from app.services.tournament_service import tournament_view
from app.services.user_common import (
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
    active_rewards: tuple[PlayerRewardView, ...] = ()


@dataclass(frozen=True)
class CheckInRewardDecisionView:
    tournament: TournamentView
    user: UserView
    active_rewards: tuple[PlayerRewardView, ...]


class TournamentCheckInService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

    async def list_today_tournaments(self, admin_telegram_id: int) -> list[TournamentView]:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            business_date = self._tournament_day()
            repository = TournamentRepository(session)
            if actor.role == UserRole.SUPERADMIN:
                tournaments = await repository.list_active_on_or_before(business_date)
            else:
                tournaments = await repository.list_active_on_date(business_date)
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_check_in(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentCheckInView:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            return await self._check_in_view(session, tournament.id, actor_role=actor.role)

    async def get_checked_in_players(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> CheckedInPlayersView:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            rows = await TournamentResultRepository(session).list_checked_in_with_users(
                tournament.id
            )
            return CheckedInPlayersView(
                tournament=tournament_view(tournament),
                players=[
                    CheckedInPlayerView(
                        display_name=row.user.display_name,
                        checked_in_at=row.result.checked_in_at,
                    )
                    for row in rows
                ],
            )

    async def search_registered(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        query: str,
    ) -> list[CheckInCandidateView]:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            players = await self._registered_candidates(session, tournament.id)
            return _score_check_in_players(players, query)

    async def search_users(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        query: str,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            checked_in_player_ids = await TournamentResultRepository(
                session
            ).list_checked_in_player_ids(tournament.id)
            registered_player_ids = await TournamentRegistrationRepository(
                session
            ).list_registered_player_ids(tournament.id)
            users = await UserRepository(session).list_active_users_for_play()
            candidates = rank_player_candidates(
                [
                    user
                    for user in users
                    if user.id not in checked_in_player_ids and user.id not in registered_player_ids
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
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            checked_in_player_ids = await TournamentResultRepository(
                session
            ).list_checked_in_player_ids(tournament.id)
            users = [
                user
                for user in await UserRepository(session).list_active_users_for_play()
                if user.id not in checked_in_player_ids
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
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            user = await self._get_active_check_in_user(session, user_id)
            return CheckInResultView(tournament_view(tournament), required_user_view(user), False)

    async def get_registered_check_in_decision(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> CheckInRewardDecisionView:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            if not await TournamentRegistrationRepository(session).exists(tournament.id, user_id):
                raise TournamentCheckInUserNotFoundError
            user = await self._get_active_check_in_user(session, user_id)
            return await self._reward_decision_view(session, tournament, user)

    async def get_existing_user_check_in_decision(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> CheckInRewardDecisionView:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            user = await self._get_active_check_in_user(session, user_id)
            if await TournamentRegistrationRepository(session).exists(tournament.id, user.id):
                raise TournamentCheckInRegisteredUserError
            return await self._reward_decision_view(session, tournament, user)

    async def get_new_user_check_in_confirmation(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> tuple[TournamentView, str]:
        validate_display_name(display_name)
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            return tournament_view(tournament), display_name

    async def check_in_registered(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
        reward_id: int | None = None,
    ) -> CheckInResultView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=admin.role,
            )
            registration_exists = await TournamentRegistrationRepository(session).exists(
                tournament.id,
                user_id,
            )
            if not registration_exists:
                raise TournamentCheckInUserNotFoundError
            user = await self._get_active_check_in_user(session, user_id)
            return await self._check_in_user(
                session,
                tournament,
                user,
                checked_in_by_user_id=admin.id,
                source=TournamentResultSource.REGISTERED,
                reward_id=reward_id,
            )

    async def check_in_user(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
        reward_id: int | None = None,
    ) -> CheckInResultView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=admin.role,
            )
            user = await self._get_active_check_in_user(session, user_id)
            registration_exists = await TournamentRegistrationRepository(session).exists(
                tournament.id,
                user.id,
            )
            return await self._check_in_user(
                session,
                tournament,
                user,
                checked_in_by_user_id=admin.id,
                source=(
                    TournamentResultSource.REGISTERED
                    if registration_exists
                    else TournamentResultSource.WALK_IN_EXISTING
                ),
                reward_id=reward_id,
            )

    async def check_in_existing_user(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
        reward_id: int | None = None,
    ) -> CheckInResultView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=admin.role,
            )
            user = await self._get_active_check_in_user(session, user_id)
            if await TournamentRegistrationRepository(session).exists(tournament.id, user.id):
                raise TournamentCheckInRegisteredUserError
            return await self._check_in_user(
                session,
                tournament,
                user,
                checked_in_by_user_id=admin.id,
                source=TournamentResultSource.WALK_IN_EXISTING,
                reward_id=reward_id,
            )

    async def create_user_and_check_in(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> CheckInResultView:
        normalized = validate_display_name(display_name)
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=admin.role,
            )
            existing_names = await UserRepository(session).list_by_display_name_normalized(
                normalized
            )
            if existing_names:
                raise TournamentCheckInDuplicateNameError
            user = create_user(display_name=display_name)
            UserRepository(session).add(user)
            try:
                await session.flush()
                await self._create_result(
                    TournamentResultRepository(session),
                    tournament_id=tournament.id,
                    player_id=user.id,
                    source=TournamentResultSource.WALK_IN_NEW,
                    checked_in_by_user_id=admin.id,
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise IdentityAlreadyExistsError("display_name") from exc
            return CheckInResultView(
                tournament_view(tournament),
                required_user_view(user),
                True,
            )

    async def _reward_decision_view(
        self,
        session: AsyncSession,
        tournament: Tournament,
        user,
    ) -> CheckInRewardDecisionView:
        rewards = await PlayerRewardService(
            self.session_factory,
            clock=self.clock,
            tournament_day_start_hour=self.tournament_day_start_hour,
        )._list_active_reward_views(session, user.id, self._tournament_day())
        return CheckInRewardDecisionView(
            tournament=tournament_view(tournament),
            user=required_user_view(user),
            active_rewards=rewards,
        )

    async def _check_in_user(
        self,
        session: AsyncSession,
        tournament: Tournament,
        user,
        *,
        checked_in_by_user_id: int,
        source: TournamentResultSource,
        reward_id: int | None,
    ) -> CheckInResultView:
        result_repository = TournamentResultRepository(session)
        if await result_repository.exists_for_tournament_and_player(tournament.id, user.id):
            return CheckInResultView(
                tournament_view(tournament),
                required_user_view(user),
                False,
            )
        if reward_id is not None:
            await PlayerRewardService(
                self.session_factory,
                clock=self.clock,
                tournament_day_start_hour=self.tournament_day_start_hour,
            ).redeem_reward_in_session(
                session,
                admin_user_id=checked_in_by_user_id,
                tournament_id=tournament.id,
                reward_id=reward_id,
                player_id=user.id,
                business_date=self._tournament_day(),
            )
        await result_repository.add_check_in(
            tournament_id=tournament.id,
            player_id=user.id,
            source=source,
            checked_in_at=self.clock.now(),
            checked_in_by_user_id=checked_in_by_user_id,
        )
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            return CheckInResultView(
                tournament_view(tournament),
                required_user_view(user),
                False,
            )
        await session.commit()
        return CheckInResultView(
            tournament_view(tournament),
            required_user_view(user),
            True,
        )

    async def _require_editable_tournament_for_actor(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        actor_role: UserRole,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise TournamentCheckInNotFoundError
        if not can_edit_open_tournament_for_actor(
            actor_role=actor_role,
            tournament_status=tournament.status,
            tournament_date=tournament.date,
            business_date=self._tournament_day(),
            admin_current_day_only=True,
        ):
            raise TournamentCheckInClosedError
        return tournament

    def _tournament_day(self) -> date:
        return resolve_tournament_day(self.clock, self.tournament_day_start_hour)

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
        checked_in_player_ids = await TournamentResultRepository(
            session
        ).list_checked_in_player_ids(tournament_id)
        users = await TournamentRegistrationRepository(
            session
        ).list_active_unchecked_registered_users(
            tournament_id,
            checked_in_player_ids,
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
        player_id: int,
        source: TournamentResultSource,
        checked_in_by_user_id: int,
    ) -> bool:
        existing = await repository.exists_for_tournament_and_player(
            tournament_id,
            player_id,
        )
        if existing:
            return False
        await repository.add_check_in(
            tournament_id=tournament_id,
            player_id=player_id,
            source=source,
            checked_in_at=self.clock.now(),
            checked_in_by_user_id=checked_in_by_user_id,
        )
        return True

    async def _check_in_view(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        actor_role: UserRole,
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
        registered_checked_in_count = sum(
            1 for row in checked_results if row.result.source == TournamentResultSource.REGISTERED
        )
        walk_in_count = sum(
            1
            for row in checked_results
            if row.result.source
            in {
                TournamentResultSource.WALK_IN_EXISTING,
                TournamentResultSource.WALK_IN_NEW,
            }
        )
        return TournamentCheckInView(
            tournament=tournament_view(tournament),
            registered_count=len(registered_users),
            registered_checked_in_count=registered_checked_in_count,
            checked_in_count=len(checked_results),
            walk_in_count=walk_in_count,
            is_superadmin_late_override=is_superadmin_late_open_tournament_override(
                actor_role=actor_role,
                tournament_status=tournament.status,
                tournament_date=tournament.date,
                business_date=self._tournament_day(),
            ),
        )


def _score_check_in_players(
    players: list[CheckInCandidateView],
    query: str,
) -> list[CheckInCandidateView]:
    candidates = rank_player_candidates(players, query, limit=10)
    return [candidate.user for candidate in candidates]


tournament_check_in_service = TournamentCheckInService(SessionFactory)
