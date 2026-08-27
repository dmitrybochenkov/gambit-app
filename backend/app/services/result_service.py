import logging
from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.factories import create_user
from app.db.models import (
    ScoringConfig,
    Tournament,
    TournamentTypeRule,
)
from app.db.models.enums import (
    KnockoutMode,
    TournamentCombinationType,
    TournamentResultSource,
    TournamentStatus,
)
from app.db.repositories.scoring_config_repository import ScoringConfigRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.tournament_combination_repository import TournamentCombinationRepository
from app.db.repositories.tournament_photo_repository import TournamentPhotoRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
)
from app.domain.tournament_close_policy import is_tournament_closeable
from app.domain.tournament_day import resolve_tournament_day
from app.domain.tournament_result_edit_policy import is_tournament_result_editable
from app.services.access_policy import access_policy
from app.services.dto.results import (
    ClosedTournamentCorrectionResultView,
    TournamentCloseReadinessView,
    TournamentCombinationPlayerView,
    TournamentCombinationsView,
    TournamentCombinationView,
    TournamentPhotoAddView,
    TournamentPhotoView,
    TournamentResultFieldChangeView,
    TournamentResultPlayerChangeView,
    TournamentResultPlayerView,
    TournamentResultSnapshotItemView,
    TournamentResultsView,
)
from app.services.dto.rewards import PrizeStackBonusSourceResultView
from app.services.dto.tournaments import TournamentView
from app.services.dto.users import UserView
from app.services.player_reward_service import PlayerRewardService
from app.services.player_search import rank_player_candidates, validate_display_name
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField
from app.services.tournament_service import tournament_view
from app.services.user_common import IdentityAlreadyExistsError, required_user_view

logger = logging.getLogger(__name__)

FOUR_OF_A_KIND_RANKS = {
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "J",
    "Q",
    "K",
    "A",
}

class ResultInvalidCombinationRankError(ValueError):
    pass


class ResultTournamentNotFoundError(ValueError):
    pass


class ResultTodayTournamentNotFoundError(ValueError):
    pass


class ResultTodayTournamentInvariantViolationError(ValueError):
    pass


class TournamentResultsEditingUnavailableError(ValueError):
    pass


class FutureTournamentCannotBeClosedError(ValueError):
    pass


class ResultUserNotFoundError(ValueError):
    pass


class ResultInvalidFundError(ValueError):
    pass


class ResultInvalidPlayerDataError(ValueError):
    pass


class ResultValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


class ResultInvalidTournamentTypeRuleError(ValueError):
    pass


class ResultDuplicateNameError(ValueError):
    pass


class ResultPlayerAlreadyAddedError(ValueError):
    pass


class ResultCombinationAlreadyExistsError(ValueError):
    pass


class ResultCombinationNotFoundError(ValueError):
    pass


TOURNAMENT_PHOTO_LIMIT = 10


class ResultService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour

    async def get_today_tournament_results(
        self,
        admin_telegram_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            business_date = self._tournament_day()
            tournaments = await TournamentRepository(session).list_active_on_date(business_date)
            if not tournaments:
                raise ResultTodayTournamentNotFoundError
            if len(tournaments) > 1:
                logger.error(
                    "Expected one active tournament for business date, got %s",
                    len(tournaments),
                    extra={
                        "business_date": business_date.isoformat(),
                        "tournament_ids": [tournament.id for tournament in tournaments],
                    },
                )
                raise ResultTodayTournamentInvariantViolationError
            return await self._results_view(session, tournaments[0].id)

    async def list_unclosed_tournaments_for_superadmin(
        self,
        superadmin_telegram_id: int,
    ) -> list[TournamentCloseReadinessView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            business_date = self._tournament_day()
            tournaments = await TournamentRepository(session).list_active_on_or_before(
                business_date
            )
            return [await self._readiness_view(session, tournament) for tournament in tournaments]

    async def list_closed_tournaments_for_superadmin(
        self,
        superadmin_telegram_id: int,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournaments = await TournamentRepository(session).list_closed()
            return [tournament_view(tournament) for tournament in tournaments]

    async def get_closed_tournament_results(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, tournament_id)
            return await self._results_view(session, tournament.id)

    async def get_closed_tournament_result_snapshot(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> tuple[TournamentResultSnapshotItemView, ...]:
        results = await self.get_closed_tournament_results(superadmin_telegram_id, tournament_id)
        return self.snapshot_from_results(results)

    async def get_tournament_results(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
            return await self._results_view(session, tournament.id)

    async def update_player_result_field(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
        field: ResultField,
        value: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
            await self._update_result_field(
                session=session,
                tournament=tournament,
                player_id=player_id,
                field=field,
                value=value,
            )
            await session.commit()
            return await self._results_view(session, tournament.id)

    async def update_closed_tournament_result_field(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        player_id: int,
        field: ResultField,
        value: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, tournament_id)
            await self._update_result_field(
                session=session,
                tournament=tournament,
                player_id=player_id,
                field=field,
                value=value,
            )
            await self._recalculate_result_points(session, tournament)
            await session.commit()
            return await self._results_view(session, tournament.id)

    async def search_closed_result_replacement_users(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        current_player_id: int,
        query: str,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, tournament_id)
            repository = TournamentResultRepository(session)
            current = await repository.get_by_tournament_and_player(
                tournament.id,
                current_player_id,
            )
            if current is None:
                raise ResultUserNotFoundError
            existing_player_ids = await repository.list_checked_in_player_ids(tournament.id)
            users = [
                user
                for user in await UserRepository(session).list_active_users_for_play()
                if user.id not in existing_player_ids
            ]
            return [
                required_user_view(candidate.user)
                for candidate in rank_player_candidates(users, query, limit=10)
            ]

    async def get_closed_result_replacement_confirmation(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        current_player_id: int,
        new_player_id: int,
    ) -> tuple[TournamentResultsView, TournamentResultPlayerView, UserView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, tournament_id)
            repository = TournamentResultRepository(session)
            if (
                await repository.get_by_tournament_and_player(tournament.id, current_player_id)
                is None
            ):
                raise ResultUserNotFoundError
            if await repository.exists_for_tournament_and_player(tournament.id, new_player_id):
                raise ResultPlayerAlreadyAddedError
            user = await UserRepository(session).get_active_by_id(new_player_id)
            if user is None:
                raise ResultUserNotFoundError
            results = await self._results_view(session, tournament.id)
            current_player = self.find_result_player(results, current_player_id)
            if current_player is None:
                raise ResultUserNotFoundError
            return results, current_player, required_user_view(user)

    async def replace_closed_tournament_result_player(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        current_player_id: int,
        new_player_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, tournament_id)
            repository = TournamentResultRepository(session)
            result = await repository.get_by_tournament_and_player(
                tournament.id,
                current_player_id,
            )
            if result is None:
                raise ResultUserNotFoundError
            if await repository.exists_for_tournament_and_player(tournament.id, new_player_id):
                raise ResultPlayerAlreadyAddedError
            user = await UserRepository(session).get_active_by_id(new_player_id)
            if user is None:
                raise ResultUserNotFoundError
            result.player_id = user.id
            await self._recalculate_result_points(session, tournament)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ResultPlayerAlreadyAddedError from exc
            return await self._results_view(session, tournament.id)

    async def finish_closed_tournament_correction(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        original_snapshot: tuple[TournamentResultSnapshotItemView, ...],
    ) -> ClosedTournamentCorrectionResultView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, tournament_id)
            current_view = await self._results_view(session, tournament.id)
            result_changes = self._result_changes(original_snapshot, current_view)
            if not result_changes:
                return ClosedTournamentCorrectionResultView(
                    tournament_id=tournament.id,
                    tournament_date=tournament.date,
                    tournament_name=tournament_view(tournament).tournament_type_name,
                    result_changes=(),
                    reward_changes=(),
                    used_reward_warnings=(),
                    player_notifications=(),
                )
            validation_errors = self._validate_game_results(current_view)
            if validation_errors:
                raise ResultValidationError(validation_errors)

            await self._recalculate_result_points(session, tournament)
            source_results: list[PrizeStackBonusSourceResultView] = []
            for player in current_view.players:
                source_results.append(
                    PrizeStackBonusSourceResultView(
                        player_id=player.player_id,
                        display_name=player.display_name,
                        telegram_id=await self._telegram_id_for_user(session, player.player_id),
                        place=player.place,
                    )
                )
            reward_result = await PlayerRewardService(
                self.session_factory,
                clock=self.clock,
                tournament_day_start_hour=self.tournament_day_start_hour,
            ).reconcile_prize_stack_bonuses_for_closed_tournament(
                session,
                tournament,
                source_results=tuple(source_results),
            )
            await session.commit()
            return ClosedTournamentCorrectionResultView(
                tournament_id=tournament.id,
                tournament_date=tournament.date,
                tournament_name=tournament_view(tournament).tournament_type_name,
                result_changes=result_changes,
                reward_changes=reward_result.reward_changes,
                used_reward_warnings=reward_result.used_reward_warnings,
                player_notifications=reward_result.player_notifications,
            )

    async def preview_tournament_close(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        tournament_fund: int | Decimal,
    ) -> TournamentResultsView:
        fund = self.validate_tournament_fund(tournament_fund)

        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closeable_tournament(session, tournament_id)

            view = await self._results_view(session, tournament.id)
            readiness = await self._readiness_view(session, tournament, view=view)
            if not readiness.is_ready:
                raise ResultValidationError(readiness.reasons)

            scoring_config, rule = await self._scoring(session, tournament)

            players = [
                replace(
                    player,
                    tournament_points=self._tournament_points(
                        tournament_fund=Decimal(fund),
                        place=player.place,
                        scoring_config=scoring_config,
                        rule=rule,
                    ),
                    knockout_points=self._knockout_points(
                        knockouts_count=player.knockouts_count,
                        big_knockouts_count=player.big_knockouts_count,
                        scoring_config=scoring_config,
                        rule=rule,
                    ),
                )
                for player in view.players
            ]

            return replace(
                view,
                tournament_fund=fund,
                players=players,
            )

    async def close_tournament(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
        tournament_fund: int | Decimal,
    ) -> TournamentResultsView:
        fund = self.validate_tournament_fund(tournament_fund)
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closeable_tournament(session, tournament_id)
            view = await self._results_view(session, tournament.id)
            readiness = await self._readiness_view(session, tournament, view=view)
            if not readiness.is_ready:
                raise ResultValidationError(readiness.reasons)

            scoring_config, rule = await self._scoring(session, tournament)
            tournament.tournament_fund = fund
            tournament.status = TournamentStatus.CLOSED
            results = await TournamentResultRepository(session).list_by_tournament(tournament.id)
            for item in results:
                item.tournament_points = self._tournament_points(
                    tournament_fund=Decimal(fund),
                    place=item.place,
                    scoring_config=scoring_config,
                    rule=rule,
                )
                item.knockout_points = self._knockout_points(
                    knockouts_count=item.knockouts_count,
                    big_knockouts_count=item.big_knockouts_count,
                    scoring_config=scoring_config,
                    rule=rule,
                )
            issued_rewards = await PlayerRewardService(
                self.session_factory,
                clock=self.clock,
                tournament_day_start_hour=self.tournament_day_start_hour,
            ).issue_prize_stack_bonuses_for_closed_tournament(
                session,
                tournament,
                issued_date=self.clock.today(),
            )
            await session.commit()
            return replace(
                await self._results_view(session, tournament.id),
                newly_issued_rewards=issued_rewards,
            )

    async def get_closeable_tournament_results(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closeable_tournament(session, tournament_id)
            return await self._results_view(session, tournament.id)

    async def validate_closeable_results(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> list[str]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closeable_tournament(session, tournament_id)
            view = await self._results_view(session, tournament.id)
            return (await self._readiness_view(session, tournament, view=view)).reasons

    async def get_close_readiness(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentCloseReadinessView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closeable_tournament(session, tournament_id)
            return await self._readiness_view(session, tournament)

    async def validate_results(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> list[str]:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
            view = await self._results_view(session, tournament.id)
            return self._validate_game_results(view)

    async def search_existing_users_for_tournament(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        query: str,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
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
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
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
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
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
            tournament = await self._require_editable_tournament(session, tournament_id)
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
            tournament = await self._require_editable_tournament(session, tournament_id)
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

    async def list_tournament_photos(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> list[TournamentPhotoView]:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            await self._require_active_tournament(session, tournament_id)
            photos = await TournamentPhotoRepository(session).list_for_tournament(tournament_id)
            return [
                TournamentPhotoView(
                    id=photo.id,
                    tournament_id=photo.tournament_id,
                    telegram_file_id=photo.telegram_file_id,
                    telegram_file_unique_id=photo.telegram_file_unique_id,
                    position=photo.position,
                )
                for photo in photos
            ]

    async def count_tournament_photos(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> int:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            await self._require_active_tournament(session, tournament_id)
            return await TournamentPhotoRepository(session).count_for_tournament(tournament_id)

    async def add_tournament_photo(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        *,
        telegram_file_id: str,
        telegram_file_unique_id: str,
    ) -> TournamentPhotoAddView:
        async with self.session_factory() as session:
            admin = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
            repository = TournamentPhotoRepository(session)
            photo_count = await repository.count_for_tournament(tournament.id)
            if photo_count >= TOURNAMENT_PHOTO_LIMIT:
                return TournamentPhotoAddView(
                    tournament_id=tournament.id,
                    photo_count=photo_count,
                    created=False,
                    limit_reached=True,
                )
            if await repository.exists_unique_file(
                tournament_id=tournament.id,
                telegram_file_unique_id=telegram_file_unique_id,
            ):
                return TournamentPhotoAddView(
                    tournament_id=tournament.id,
                    photo_count=photo_count,
                    created=False,
                )
            await repository.add(
                tournament_id=tournament.id,
                telegram_file_id=telegram_file_id,
                telegram_file_unique_id=telegram_file_unique_id,
                uploaded_by_user_id=admin.id,
                position=await repository.next_position(tournament.id),
            )
            await session.commit()
            return TournamentPhotoAddView(
                tournament_id=tournament.id,
                photo_count=photo_count + 1,
                created=True,
            )

    async def delete_tournament_photos(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
            await TournamentPhotoRepository(session).delete_all_for_tournament(tournament.id)
            await session.commit()
            return await self._results_view(session, tournament.id)

    async def get_tournament_combinations(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentCombinationsView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
            return await self._combinations_view(session, tournament)

    async def add_tournament_combination(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        player_id: int,
        combination_type: TournamentCombinationType,
        rank: str | None = None,
    ) -> TournamentCombinationsView:
        if combination_type == TournamentCombinationType.FOUR_OF_A_KIND:
            if rank not in FOUR_OF_A_KIND_RANKS:
                raise ResultInvalidCombinationRankError
        elif rank is not None:
            raise ResultInvalidCombinationRankError
        
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
            result = await TournamentResultRepository(session).get_by_tournament_and_player(
                tournament.id,
                player_id,
            )
            if result is None:
                raise ResultUserNotFoundError
            try:
                await TournamentCombinationRepository(session).add(
                    tournament_id=tournament.id,
                    player_id=player_id,
                    combination_type=combination_type,
                    rank=rank,
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ResultCombinationAlreadyExistsError from exc
            return await self._combinations_view(session, tournament)

    async def delete_tournament_combination(
        self,
        admin_telegram_id: int,
        tournament_id: int,
        combination_id: int,
    ) -> TournamentCombinationsView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament(session, tournament_id)
            deleted = await TournamentCombinationRepository(session).delete_by_id(
                tournament_id=tournament_id,
                combination_id=combination_id,
            )
            if not deleted:
                raise ResultCombinationNotFoundError
            await session.commit()
            return await self._combinations_view(session, tournament)

    async def _require_active_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None or tournament.status != TournamentStatus.ACTIVE:
            raise ResultTournamentNotFoundError
        return tournament

    async def _require_editable_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await self._require_active_tournament(session, tournament_id)
        if not is_tournament_result_editable(tournament, self._tournament_day()):
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

    async def _require_closed_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None or tournament.status != TournamentStatus.CLOSED:
            raise ResultTournamentNotFoundError
        return tournament

    async def _update_result_field(
        self,
        *,
        session: AsyncSession,
        tournament: Tournament,
        player_id: int,
        field: ResultField,
        value: int,
    ) -> None:
        repository = TournamentResultRepository(session)
        result = await repository.get_by_tournament_and_player(tournament.id, player_id)
        if result is None:
            raise ResultUserNotFoundError

        knockout_mode, supports_bonus_points = await self._result_capabilities(session, tournament)
        if not is_result_field_allowed(
            field=field,
            knockout_mode=knockout_mode.value,
            supports_bonus_points=supports_bonus_points,
        ):
            raise ResultInvalidPlayerDataError
        if value < 0:
            raise ResultInvalidPlayerDataError
        if field == ResultField.PLACE and value not in {1, 2, 3, 4, 5}:
            raise ResultInvalidPlayerDataError

        if field == ResultField.PLACE:
            occupied = await repository.list_by_tournament_and_place(
                tournament.id,
                value,
                exclude_result_id=result.id,
            )
            for occupied_result in occupied:
                occupied_result.place = None
            result.place = value
        elif field == ResultField.KNOCKOUTS:
            result.knockouts_count = value
        elif field == ResultField.BIG_KNOCKOUTS:
            result.big_knockouts_count = value
        elif field == ResultField.BONUS:
            result.bonus_points = value

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
            photo_count=await TournamentPhotoRepository(session).count_for_tournament(
                tournament.id
            ),
            knockout_mode=knockout_mode.value,
            supports_bonus_points=supports_bonus_points,
        )

    async def _readiness_view(
        self,
        session: AsyncSession,
        tournament: Tournament,
        *,
        view: TournamentResultsView | None = None,
    ) -> TournamentCloseReadinessView:
        results = view or await self._results_view(session, tournament.id)
        validation_errors = self._validate_game_results(results)
        has_checkins = bool(results.players)
        has_photos = results.photo_count > 0
        reasons: list[str] = []
        if not has_checkins:
            reasons.append("Турнир ещё не начался.")
        if has_checkins and any(error.startswith("Введи места:") for error in validation_errors):
            reasons.append("Не введены призовые места.")
        if not has_photos:
            reasons.append("Фото не добавлены.")
        other_errors = [
            error
            for error in validation_errors
            if not error.startswith("Введи места:") and error != "Нет участников турнира."
        ]
        if other_errors:
            reasons.append("Результаты заполнены не полностью.")
        return TournamentCloseReadinessView(
            tournament=tournament_view(tournament),
            is_ready=not reasons,
            photo_count=results.photo_count,
            has_photos=has_photos,
            has_checkins=has_checkins,
            validation_errors=validation_errors,
            reasons=reasons,
        )

    async def _combinations_view(
        self,
        session: AsyncSession,
        tournament: Tournament,
    ) -> TournamentCombinationsView:
        repository = TournamentCombinationRepository(session)
        combinations = await repository.list_with_users(tournament.id)
        players = await repository.list_player_candidates(tournament.id)
        return TournamentCombinationsView(
            tournament=tournament_view(tournament),
            combinations=[
                TournamentCombinationView(
                    id=row.combination.id,
                    tournament_id=row.combination.tournament_id,
                    player_id=row.user.id,
                    display_name=row.user.display_name,
                    combination_type=row.combination.combination_type,
                    rank=row.combination.rank,
                )
                for row in combinations
            ],
            players=[
                TournamentCombinationPlayerView(
                    player_id=player.id,
                    display_name=player.display_name,
                )
                for player in players
            ],
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

    async def _recalculate_result_points(
        self,
        session: AsyncSession,
        tournament: Tournament,
    ) -> None:
        if tournament.tournament_fund is None:
            raise ResultInvalidFundError
        scoring_config, rule = await self._scoring(session, tournament)
        results = await TournamentResultRepository(session).list_by_tournament(tournament.id)
        for item in results:
            item.tournament_points = self._tournament_points(
                tournament_fund=Decimal(tournament.tournament_fund),
                place=item.place,
                scoring_config=scoring_config,
                rule=rule,
            )
            item.knockout_points = self._knockout_points(
                knockouts_count=item.knockouts_count,
                big_knockouts_count=item.big_knockouts_count,
                scoring_config=scoring_config,
                rule=rule,
            )

    @staticmethod
    async def _telegram_id_for_user(
        session: AsyncSession,
        player_id: int,
    ) -> int | None:
        user = await UserRepository(session).get_by_id(player_id)
        return user.telegram_id if user is not None else None

    @staticmethod
    def snapshot_from_results(
        results: TournamentResultsView,
    ) -> tuple[TournamentResultSnapshotItemView, ...]:
        return tuple(
            TournamentResultSnapshotItemView(
                player_id=player.player_id,
                display_name=player.display_name,
                place=player.place,
                knockouts_count=player.knockouts_count,
                big_knockouts_count=player.big_knockouts_count,
                bonus_points=player.bonus_points,
            )
            for player in results.players
        )

    @staticmethod
    def snapshot_from_payload(
        payload: object,
    ) -> tuple[TournamentResultSnapshotItemView, ...]:
        if not isinstance(payload, list):
            return ()
        snapshot = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            snapshot.append(
                TournamentResultSnapshotItemView(
                    player_id=int(item["player_id"]),
                    display_name=str(item["display_name"]),
                    place=item["place"] if item["place"] is None else int(item["place"]),
                    knockouts_count=int(item["knockouts_count"]),
                    big_knockouts_count=int(item["big_knockouts_count"]),
                    bonus_points=int(item["bonus_points"]),
                )
            )
        return tuple(snapshot)

    @staticmethod
    def snapshot_to_payload(
        snapshot: tuple[TournamentResultSnapshotItemView, ...],
    ) -> list[dict[str, object]]:
        return [
            {
                "player_id": item.player_id,
                "display_name": item.display_name,
                "place": item.place,
                "knockouts_count": item.knockouts_count,
                "big_knockouts_count": item.big_knockouts_count,
                "bonus_points": item.bonus_points,
            }
            for item in snapshot
        ]

    @staticmethod
    def _result_changes(
        snapshot: tuple[TournamentResultSnapshotItemView, ...],
        current: TournamentResultsView,
    ) -> tuple[TournamentResultPlayerChangeView, ...]:
        before_by_player = {item.player_id: item for item in snapshot}
        current_by_player = {player.player_id: player for player in current.players}
        removed = [item for item in snapshot if item.player_id not in current_by_player]
        added = [player for player in current.players if player.player_id not in before_by_player]
        paired_added_player_ids: set[int] = set()
        paired_removed_player_ids: set[int] = set()
        changes: list[TournamentResultPlayerChangeView] = []
        for before in removed:
            replacement = next(
                (
                    player
                    for player in added
                    if player.player_id not in paired_added_player_ids
                    and ResultService._snapshot_values(before)
                    == ResultService._result_values(player)
                ),
                None,
            )
            if replacement is None:
                continue
            paired_removed_player_ids.add(before.player_id)
            paired_added_player_ids.add(replacement.player_id)
            changes.append(
                TournamentResultPlayerChangeView(
                    player_id=replacement.player_id,
                    display_name=replacement.display_name,
                    fields=(
                        TournamentResultFieldChangeView(
                            label="Игрок",
                            before=before.display_name,
                            after=replacement.display_name,
                        ),
                    ),
                )
            )
        for player in current.players:
            if player.player_id in paired_added_player_ids:
                continue
            before = before_by_player.get(player.player_id)
            if before is None:
                changes.append(
                    TournamentResultPlayerChangeView(
                        player_id=player.player_id,
                        display_name=player.display_name,
                        fields=(
                            TournamentResultFieldChangeView(
                                label="Игрок",
                                before="—",
                                after=player.display_name,
                            ),
                        ),
                    )
                )
                continue
            fields = tuple(
                field
                for field in (
                    ResultService._field_change("Место", before.place, player.place),
                    ResultService._field_change(
                        "КО",
                        before.knockouts_count,
                        player.knockouts_count,
                    ),
                    ResultService._field_change(
                        "БКО",
                        before.big_knockouts_count,
                        player.big_knockouts_count,
                    ),
                    ResultService._field_change(
                        "Бонус",
                        before.bonus_points,
                        player.bonus_points,
                    ),
                )
                if field is not None
            )
            if fields:
                changes.append(
                    TournamentResultPlayerChangeView(
                        player_id=player.player_id,
                        display_name=player.display_name,
                        fields=fields,
                    )
                )
        for before in snapshot:
            if before.player_id in paired_removed_player_ids:
                continue
            if before.player_id not in current_by_player:
                changes.append(
                    TournamentResultPlayerChangeView(
                        player_id=before.player_id,
                        display_name=before.display_name,
                        fields=(
                            TournamentResultFieldChangeView(
                                label="Игрок",
                                before=before.display_name,
                                after="—",
                            ),
                        ),
                    )
                )
        return tuple(changes)

    @staticmethod
    def _snapshot_values(
        item: TournamentResultSnapshotItemView,
    ) -> tuple[int | None, int, int, int]:
        return (
            item.place,
            item.knockouts_count,
            item.big_knockouts_count,
            item.bonus_points,
        )

    @staticmethod
    def _result_values(
        item: TournamentResultPlayerView,
    ) -> tuple[int | None, int, int, int]:
        return (
            item.place,
            item.knockouts_count,
            item.big_knockouts_count,
            item.bonus_points,
        )

    @staticmethod
    def _field_change(
        label: str,
        before: int | None,
        after: int | None,
    ) -> TournamentResultFieldChangeView | None:
        if before == after:
            return None
        return TournamentResultFieldChangeView(
            label=label,
            before="—" if before is None else str(before),
            after="—" if after is None else str(after),
        )

    @staticmethod
    def _validate_game_results(results: TournamentResultsView) -> list[str]:
        errors: list[str] = []
        if not results.players:
            errors.append("Нет участников турнира.")
        places = [player.place for player in results.players if player.place is not None]
        required_places = set(results.required_places)
        missing_places = sorted(required_places - set(places))
        if missing_places:
            errors.append("Введи места: " + ", ".join(str(place) for place in missing_places) + ".")
        duplicates = sorted({place for place in places if places.count(place) > 1})
        if duplicates:
            errors.append(
                "Дублируются места: " + ", ".join(str(place) for place in duplicates) + "."
            )
        small_knockouts = sum(player.knockouts_count for player in results.players)
        big_knockouts = sum(player.big_knockouts_count for player in results.players)
        if results.knockout_mode == KnockoutMode.SMALL.value and small_knockouts <= 0:
            errors.append("Введи хотя бы один 🥊.")
        if (
            results.knockout_mode == KnockoutMode.SMALL_BIG.value
            and (small_knockouts + big_knockouts) <= 0
        ):
            errors.append("Введи хотя бы один 🥊 или 👑🥊.")
        return errors

    @staticmethod
    def validate_tournament_fund(value: int | Decimal) -> int:
        try:
            fund = Decimal(value)
        except Exception as exc:
            raise ResultInvalidFundError from exc
        if fund != fund.to_integral_value() or fund <= 0 or fund % Decimal("10") != 0:
            raise ResultInvalidFundError
        return int(fund)

    async def _scoring(
        self,
        session: AsyncSession,
        tournament: Tournament,
    ) -> tuple[ScoringConfig, TournamentTypeRule | None]:
        season = await SeasonRepository(session).get_by_id(tournament.season_id)
        if season is None:
            raise ResultTournamentNotFoundError
        scoring_config = await ScoringConfigRepository(session).get_by_id(season.scoring_config_id)
        if scoring_config is None:
            raise ResultTournamentNotFoundError
        return scoring_config, await TournamentTypeRepository(session).get_rule(
            tournament.tournament_type_id
        )

    @staticmethod
    def _tournament_points(
        tournament_fund: Decimal,
        place: int | None,
        scoring_config: ScoringConfig,
        rule: TournamentTypeRule | None,
    ) -> Decimal:
        if place is None or place not in {1, 2, 3, 4, 5}:
            return Decimal("0")
        coefficient = getattr(scoring_config, f"place_{place}_coefficient")
        multiplier = rule.points_multiplier if rule is not None else Decimal("1")
        if rule is not None and rule.prize_place_multiplier_places:
            try:
                places = set(parse_prize_multiplier_places(rule.prize_place_multiplier_places))
            except PrizeMultiplierPlacesError as exc:
                raise ResultInvalidTournamentTypeRuleError from exc
            if place in places:
                multiplier *= rule.prize_place_multiplier
        return (tournament_fund * coefficient * multiplier).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _knockout_points(
        knockouts_count: int,
        big_knockouts_count: int,
        scoring_config: ScoringConfig,
        rule: TournamentTypeRule | None,
    ) -> Decimal:
        if rule is None or rule.knockout_mode == KnockoutMode.NONE:
            return Decimal("0")
        if rule.knockout_mode == KnockoutMode.SMALL:
            points = knockouts_count * scoring_config.knockout_small_points
        else:
            points = (
                knockouts_count * scoring_config.knockout_small_points
                + big_knockouts_count * scoring_config.knockout_big_points
            )
        return Decimal(points).quantize(Decimal("0.01"))

    @staticmethod
    def find_result_player(
        results: TournamentResultsView,
        player_id: int,
    ) -> TournamentResultPlayerView | None:
        return next((player for player in results.players if player.player_id == player_id), None)

    @staticmethod
    def result_field_is_allowed(
        knockout_mode: str,
        field: ResultField,
        supports_bonus_points: bool = False,
    ) -> bool:
        return is_result_field_allowed(
            field=field,
            knockout_mode=knockout_mode,
            supports_bonus_points=supports_bonus_points,
        )

    @staticmethod
    def editable_result_fields(results: TournamentResultsView) -> list[ResultField]:
        return [
            field
            for field in (
                ResultField.PLACE,
                ResultField.KNOCKOUTS,
                ResultField.BIG_KNOCKOUTS,
                ResultField.BONUS,
            )
            if ResultService.result_field_is_allowed(
                results.knockout_mode,
                field,
                results.supports_bonus_points,
            )
        ]

    @staticmethod
    def occupied_result_places(results: TournamentResultsView) -> set[int]:
        return {player.place for player in results.players if player.place is not None}


result_service = ResultService(SessionFactory)
