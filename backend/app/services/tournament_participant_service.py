from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.factories import create_user
from app.db.models import Tournament
from app.db.models.enums import (
    KnockoutMode,
    PlayerRewardType,
    TournamentResultSource,
    TournamentStatus,
    UserRole,
)
from app.db.repositories.player_reward_repository import PlayerRewardRepository
from app.db.repositories.tournament_registration_repository import (
    TournamentRegistrationRepository,
)
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.domain.open_tournament_edit_policy import can_edit_open_tournament_for_actor
from app.domain.tournament_close_policy import is_tournament_closeable
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.results import (
    OpenTournamentPlayerDeletePreviewView,
    OpenTournamentPlayerDeleteResultView,
    TournamentResultPlayerView,
    TournamentResultsView,
)
from app.services.dto.tournaments import TournamentView
from app.services.dto.users import UserView
from app.services.pagination import Page, pagination_service
from app.services.player_search import rank_player_candidates, validate_display_name
from app.services.result_errors import (
    FutureTournamentCannotBeClosedError,
    ResultDuplicateNameError,
    ResultPlayerAlreadyAddedError,
    ResultPlayerRewardConflictError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    TournamentResultsEditingUnavailableError,
)
from app.services.tournament_combination_service import TournamentCombinationService
from app.services.tournament_photo_service import TournamentPhotoService
from app.services.tournament_service import tournament_view
from app.services.user_common import IdentityAlreadyExistsError, required_user_view

OPEN_TOURNAMENT_DELETE_PLAYER_PAGE_SIZE = 6


class TournamentParticipantService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour
        self._photo_service = TournamentPhotoService(
            session_factory,
            clock=clock,
            tournament_day_start_hour=tournament_day_start_hour,
        )
        self._combination_service = TournamentCombinationService(
            session_factory,
            clock=clock,
            tournament_day_start_hour=tournament_day_start_hour,
        )

    async def search_existing_users_for_tournament(
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
            existing_player_ids = await TournamentResultRepository(
                session
            ).list_checked_in_player_ids(tournament.id)
            users = [
                user
                for user in await UserRepository(session).list_active_users_for_play()
                if user.id not in existing_player_ids
            ]
            return [
                required_user_view(candidate.user)
                for candidate in rank_player_candidates(users, query, limit=10)
            ]

    async def get_existing_player_add_confirmation(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> tuple[TournamentView, UserView]:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            user = await UserRepository(session).get_active_by_id(user_id)
            if user is None:
                raise ResultUserNotFoundError
            return tournament_view(tournament), required_user_view(user)

    async def get_new_player_add_confirmation(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> tuple[TournamentView, str]:
        normalized = validate_display_name(display_name)
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            existing_names = await UserRepository(session).list_by_display_name_normalized(
                normalized
            )
            if existing_names:
                raise ResultDuplicateNameError
            return tournament_view(tournament), display_name

    async def add_existing_player_to_tournament(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        user_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=admin.role,
            )
            user = await UserRepository(session).get_active_by_id(user_id)
            if user is None:
                raise ResultUserNotFoundError
            created = await self._create_result(
                TournamentResultRepository(session),
                tournament_id=tournament.id,
                player_id=user.id,
                source=TournamentResultSource.WALK_IN_EXISTING,
                checked_in_by_user_id=admin.id,
            )
            if not created:
                raise ResultPlayerAlreadyAddedError
            await session.commit()
            return await self._results_view(session, tournament.id)

    async def add_new_player_to_tournament(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        display_name: str,
    ) -> TournamentResultsView:
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
                raise ResultDuplicateNameError
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
            return await self._results_view(session, tournament.id)

    async def get_open_tournament_player_delete_preview(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        player_id: int,
    ) -> OpenTournamentPlayerDeletePreviewView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closeable_tournament(session, tournament_id)
            player = await self._require_tournament_result_player(
                session,
                tournament_id=tournament.id,
                player_id=player_id,
            )
            combinations_count = await self._combination_service.count_for_player_in_session(
                session,
                tournament_id=tournament.id,
                player_id=player_id,
            )
            return OpenTournamentPlayerDeletePreviewView(
                tournament=tournament_view(tournament),
                player=player,
                combinations_count=combinations_count,
            )

    async def list_open_tournament_players_for_delete(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        *,
        page: int,
        page_size: int = OPEN_TOURNAMENT_DELETE_PLAYER_PAGE_SIZE,
    ) -> Page[TournamentResultPlayerView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closeable_tournament(session, tournament_id)
            results = await self._results_view(session, tournament.id)
            return pagination_service.paginate(results.players, page=page, page_size=page_size)

    async def delete_player_from_open_tournament(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        player_id: int,
    ) -> OpenTournamentPlayerDeleteResultView:
        async with self.session_factory() as session:
            try:
                await access_policy.require_superadmin(session, superadmin_telegram_id)
                tournament = await self._require_closeable_tournament(session, tournament_id)
                player = await self._require_tournament_result_player(
                    session,
                    tournament_id=tournament.id,
                    player_id=player_id,
                )
                if await PlayerRewardRepository(session).exists_for_source(
                    source_tournament_id=tournament.id,
                    player_id=player_id,
                    reward_type=PlayerRewardType.PRIZE_STACK_BONUS,
                ):
                    raise ResultPlayerRewardConflictError

                deleted_combinations_count = (
                    await self._combination_service.delete_for_player_in_session(
                        session,
                        tournament_id=tournament.id,
                        player_id=player_id,
                    )
                )
                deleted_registration = await TournamentRegistrationRepository(
                    session
                ).delete_by_tournament_and_player(tournament.id, player_id)
                result = await TournamentResultRepository(session).get_by_tournament_and_player(
                    tournament.id,
                    player_id,
                )
                if result is None:
                    raise ResultUserNotFoundError
                await TournamentResultRepository(session).delete(result)
                await session.commit()
                return OpenTournamentPlayerDeleteResultView(
                    tournament=tournament_view(tournament),
                    player=player,
                    deleted_registration=deleted_registration,
                    deleted_combinations_count=deleted_combinations_count,
                )
            except Exception:
                await session.rollback()
                raise

    async def _require_active_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None or tournament.status != TournamentStatus.ACTIVE:
            raise ResultTournamentNotFoundError
        return tournament

    async def _require_editable_tournament_for_actor(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        actor_role: UserRole,
    ) -> Tournament:
        tournament = await self._require_active_tournament(session, tournament_id)
        if not can_edit_open_tournament_for_actor(
            actor_role=actor_role,
            tournament_status=tournament.status,
            tournament_date=tournament.date,
            business_date=self._tournament_day(),
            admin_current_day_only=False,
        ):
            raise TournamentResultsEditingUnavailableError
        return tournament

    async def _require_closeable_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await self._require_active_tournament(session, tournament_id)
        if not is_tournament_closeable(tournament, self._tournament_day()):
            raise FutureTournamentCannotBeClosedError
        return tournament

    def _tournament_day(self) -> date:
        return resolve_tournament_day(self.clock, self.tournament_day_start_hour)

    async def _result_capabilities(
        self,
        session: AsyncSession,
        tournament: Tournament,
    ) -> tuple[KnockoutMode, bool]:
        rule_row = await TournamentTypeRepository(session).get_rule_capabilities(
            tournament.tournament_type_id
        )
        if rule_row is None:
            return KnockoutMode.NONE, False
        return rule_row.knockout_mode, bool(rule_row.supports_bonus_points)

    async def _results_view(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> TournamentResultsView:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None:
            raise ResultTournamentNotFoundError
        result_rows = await TournamentResultRepository(session).list_with_users(
            tournament_id,
            order_by_user_id=True,
        )
        players = [
            TournamentResultPlayerView(
                player_id=row.user.id,
                display_name=row.user.display_name,
                place=row.result.place,
                knockouts_count=row.result.knockouts_count,
                big_knockouts_count=row.result.big_knockouts_count,
                bonus_points=row.result.bonus_points,
                tournament_points=row.result.tournament_points,
                knockout_points=row.result.knockout_points,
                result_id=row.result.id,
            )
            for row in result_rows
        ]
        players.sort(key=lambda player: player.display_name.casefold())
        knockout_mode, supports_bonus_points = await self._result_capabilities(
            session,
            tournament,
        )
        return TournamentResultsView(
            tournament=tournament_view(tournament),
            tournament_fund=tournament.tournament_fund,
            players=players,
            photo_count=await self._photo_service.count_for_tournament_in_session(
                session,
                tournament.id,
            ),
            knockout_mode=knockout_mode.value,
            supports_bonus_points=supports_bonus_points,
        )

    async def _require_tournament_result_player(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        player_id: int,
    ) -> TournamentResultPlayerView:
        row = await TournamentResultRepository(session).get_by_tournament_and_player(
            tournament_id,
            player_id,
        )
        if row is None:
            raise ResultUserNotFoundError
        user = await UserRepository(session).get_by_id(player_id)
        if user is None:
            raise ResultUserNotFoundError
        return TournamentResultPlayerView(
            player_id=user.id,
            display_name=user.display_name,
            place=row.place,
            knockouts_count=row.knockouts_count,
            big_knockouts_count=row.big_knockouts_count,
            bonus_points=row.bonus_points,
            tournament_points=row.tournament_points,
            knockout_points=row.knockout_points,
            result_id=row.id,
        )

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


tournament_participant_service = TournamentParticipantService(SessionFactory)
