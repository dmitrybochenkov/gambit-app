from dataclasses import replace
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import Tournament
from app.db.models.enums import TournamentResultSource, TournamentStatus
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.services.access_policy import access_policy
from app.services.dto.results import (
    ClosedTournamentCorrectionDraftView,
    ClosedTournamentCorrectionResultView,
    TournamentResultFieldChangeView,
    TournamentResultPlayerChangeView,
    TournamentResultPlayerView,
    TournamentResultSnapshotItemView,
    TournamentResultsView,
)
from app.services.dto.rewards import (
    PlayerRewardCorrectionResultView,
    PrizeStackBonusSourceResultView,
)
from app.services.dto.tournaments import TournamentView
from app.services.dto.users import UserView
from app.services.player_reward_service import PlayerRewardService
from app.services.player_search import rank_player_candidates
from app.services.result_errors import (
    ClosedTournamentCorrectionStaleError,
    ResultInvalidFundError,
    ResultInvalidPlayerDataError,
    ResultPlayerAlreadyAddedError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    ResultValidationError,
)
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField
from app.services.result_service import _USE_PERSISTED_TOURNAMENT_FUND, ResultService
from app.services.tournament_combination_service import TournamentCombinationService
from app.services.tournament_photo_service import TournamentPhotoService
from app.services.tournament_service import tournament_view
from app.services.user_common import required_user_view


class ClosedTournamentCorrectionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
        tournament_day_start_hour: int = settings.tournament_day_start_hour,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tournament_day_start_hour = tournament_day_start_hour
        self._result_service = ResultService(
            session_factory,
            clock=clock,
            tournament_day_start_hour=tournament_day_start_hour,
        )
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
            return await self._result_service._results_view(session, tournament.id)

    async def get_closed_tournament_result_snapshot(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> tuple[TournamentResultSnapshotItemView, ...]:
        results = await self.get_closed_tournament_results(superadmin_telegram_id, tournament_id)
        return self.snapshot_from_results(results)

    async def begin_closed_tournament_correction(
        self,
        superadmin_telegram_id: int,
        tournament_id: int,
    ) -> ClosedTournamentCorrectionDraftView:
        results = await self.get_closed_tournament_results(superadmin_telegram_id, tournament_id)
        snapshot = self.snapshot_from_results(results)
        return ClosedTournamentCorrectionDraftView(
            tournament_id=tournament_id,
            original_tournament_fund=results.tournament_fund,
            proposed_tournament_fund=results.tournament_fund,
            original_results=snapshot,
            proposed_results=snapshot,
        )

    async def get_closed_tournament_draft_results(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            return await self._results_view_from_snapshot(
                session,
                tournament,
                draft.proposed_results,
                tournament_fund=draft.proposed_tournament_fund,
            )

    async def update_closed_tournament_draft_result_field(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        player_id: int,
        field: ResultField,
        value: int,
    ) -> ClosedTournamentCorrectionDraftView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            proposed = list(draft.proposed_results)
            index = next(
                (
                    item_index
                    for item_index, item in enumerate(proposed)
                    if item.player_id == player_id
                ),
                None,
            )
            if index is None:
                raise ResultUserNotFoundError
            await self._validate_result_field(session, tournament, field, value)
            item = proposed[index]
            if field == ResultField.PLACE:
                proposed = [
                    replace(other, place=None)
                    if other.player_id != player_id and other.place == value
                    else other
                    for other in proposed
                ]
                item = proposed[index]
                proposed[index] = replace(item, place=value)
            elif field == ResultField.KNOCKOUTS:
                proposed[index] = replace(item, knockouts_count=value)
            elif field == ResultField.BIG_KNOCKOUTS:
                proposed[index] = replace(item, big_knockouts_count=value)
            elif field == ResultField.BONUS:
                proposed[index] = replace(item, bonus_points=value)
            return replace(draft, proposed_results=tuple(proposed))

    async def replace_closed_tournament_draft_result_player(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        current_player_id: int,
        new_player_id: int,
    ) -> ClosedTournamentCorrectionDraftView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            proposed = list(draft.proposed_results)
            index = next(
                (
                    item_index
                    for item_index, item in enumerate(proposed)
                    if item.player_id == current_player_id
                ),
                None,
            )
            if index is None:
                raise ResultUserNotFoundError
            if any(item.player_id == new_player_id for item in proposed):
                raise ResultPlayerAlreadyAddedError
            user = await UserRepository(session).get_active_by_id(new_player_id)
            if user is None:
                raise ResultUserNotFoundError
            proposed[index] = replace(
                proposed[index],
                player_id=user.id,
                display_name=user.display_name,
            )
            return replace(draft, proposed_results=tuple(proposed))

    async def update_closed_tournament_draft_fund(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        tournament_fund: int | Decimal,
    ) -> ClosedTournamentCorrectionDraftView:
        fund = ResultService.validate_tournament_fund(tournament_fund)
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            return replace(draft, proposed_tournament_fund=fund)

    async def search_closed_draft_add_player_users(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        query: str,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            existing_player_ids = {item.player_id for item in draft.proposed_results}
            users = [
                user
                for user in await UserRepository(session).list_active_users_for_play()
                if user.id not in existing_player_ids
            ]
            return [
                required_user_view(candidate.user)
                for candidate in rank_player_candidates(users, query, limit=10)
            ]

    async def add_closed_tournament_draft_existing_player(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        user_id: int,
    ) -> ClosedTournamentCorrectionDraftView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            if any(item.player_id == user_id for item in draft.proposed_results):
                raise ResultPlayerAlreadyAddedError
            user = await UserRepository(session).get_active_by_id(user_id)
            if user is None:
                raise ResultUserNotFoundError
            return replace(
                draft,
                proposed_results=(
                    *draft.proposed_results,
                    TournamentResultSnapshotItemView(
                        player_id=user.id,
                        display_name=user.display_name,
                        place=None,
                        knockouts_count=0,
                        big_knockouts_count=0,
                        bonus_points=0,
                        result_id=None,
                    ),
                ),
            )

    async def get_closed_draft_add_player_confirmation(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        user_id: int,
    ) -> tuple[TournamentResultsView, UserView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            if any(item.player_id == user_id for item in draft.proposed_results):
                raise ResultPlayerAlreadyAddedError
            user = await UserRepository(session).get_active_by_id(user_id)
            if user is None:
                raise ResultUserNotFoundError
            return (
                await self._results_view_from_snapshot(
                    session,
                    tournament,
                    draft.proposed_results,
                    tournament_fund=draft.proposed_tournament_fund,
                ),
                required_user_view(user),
            )

    async def delete_closed_tournament_draft_player(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        player_id: int,
    ) -> ClosedTournamentCorrectionDraftView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            if not any(item.player_id == player_id for item in draft.proposed_results):
                raise ResultUserNotFoundError
            return replace(
                draft,
                proposed_results=tuple(
                    item for item in draft.proposed_results if item.player_id != player_id
                ),
            )

    async def search_closed_draft_replacement_users(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        current_player_id: int,
        query: str,
    ) -> list[UserView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            if not any(item.player_id == current_player_id for item in draft.proposed_results):
                raise ResultUserNotFoundError
            existing_player_ids = {item.player_id for item in draft.proposed_results}
            users = [
                user
                for user in await UserRepository(session).list_active_users_for_play()
                if user.id not in existing_player_ids
            ]
            return [
                required_user_view(candidate.user)
                for candidate in rank_player_candidates(users, query, limit=10)
            ]

    async def get_closed_draft_replacement_confirmation(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
        current_player_id: int,
        new_player_id: int,
    ) -> tuple[TournamentResultsView, TournamentResultPlayerView, UserView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            results = await self._results_view_from_snapshot(
                session,
                tournament,
                draft.proposed_results,
            )
            current_player = ResultService.find_result_player(results, current_player_id)
            if current_player is None:
                raise ResultUserNotFoundError
            if any(item.player_id == new_player_id for item in draft.proposed_results):
                raise ResultPlayerAlreadyAddedError
            user = await UserRepository(session).get_active_by_id(new_player_id)
            if user is None:
                raise ResultUserNotFoundError
            return results, current_player, required_user_view(user)

    async def build_closed_tournament_correction_preview(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
    ) -> ClosedTournamentCorrectionResultView:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            tournament = await self._require_closed_tournament(session, draft.tournament_id)
            await self._validate_draft_current(session, tournament, draft)
            proposed_view = await self._results_view_from_snapshot(
                session,
                tournament,
                draft.proposed_results,
                tournament_fund=draft.proposed_tournament_fund,
            )
            before_view = await self._results_view_from_snapshot(
                session,
                tournament,
                draft.original_results,
                tournament_fund=draft.original_tournament_fund,
            )
            result_changes = self._result_changes(draft.original_results, proposed_view)
            fund_changed = draft.original_tournament_fund != draft.proposed_tournament_fund
            if not result_changes and not fund_changed:
                return ClosedTournamentCorrectionResultView(
                    tournament_id=tournament.id,
                    tournament_date=tournament.date,
                    tournament_name=tournament_view(tournament).tournament_type_name,
                    result_changes=(),
                    reward_changes=(),
                    used_reward_warnings=(),
                    player_notifications=(),
                    before_results=before_view,
                    after_results=proposed_view,
                    fund_before=draft.original_tournament_fund,
                    fund_after=draft.proposed_tournament_fund,
                )
            validation_errors = ResultService._validate_game_results(proposed_view)
            if validation_errors:
                raise ResultValidationError(validation_errors)
            reward_result = await self._preview_reward_reconciliation(
                session,
                tournament,
                proposed_view,
            )
            return ClosedTournamentCorrectionResultView(
                tournament_id=tournament.id,
                tournament_date=tournament.date,
                tournament_name=tournament_view(tournament).tournament_type_name,
                result_changes=result_changes,
                reward_changes=reward_result.reward_changes,
                used_reward_warnings=reward_result.used_reward_warnings,
                player_notifications=reward_result.player_notifications,
                before_results=before_view,
                after_results=proposed_view,
                fund_before=draft.original_tournament_fund,
                fund_after=draft.proposed_tournament_fund,
            )

    async def apply_closed_tournament_correction(
        self,
        superadmin_telegram_id: int,
        draft: ClosedTournamentCorrectionDraftView,
    ) -> ClosedTournamentCorrectionResultView:
        async with self.session_factory() as session:
            try:
                superadmin = await access_policy.require_superadmin(session, superadmin_telegram_id)
                tournament = await self._require_closed_tournament(session, draft.tournament_id)
                await self._validate_draft_current(session, tournament, draft)
                proposed_view = await self._results_view_from_snapshot(
                    session,
                    tournament,
                    draft.proposed_results,
                    tournament_fund=draft.proposed_tournament_fund,
                )
                before_view = await self._results_view_from_snapshot(
                    session,
                    tournament,
                    draft.original_results,
                    tournament_fund=draft.original_tournament_fund,
                )
                result_changes = self._result_changes(draft.original_results, proposed_view)
                fund_changed = draft.original_tournament_fund != draft.proposed_tournament_fund
                if not result_changes and not fund_changed:
                    return ClosedTournamentCorrectionResultView(
                        tournament_id=tournament.id,
                        tournament_date=tournament.date,
                        tournament_name=tournament_view(tournament).tournament_type_name,
                        result_changes=(),
                        reward_changes=(),
                        used_reward_warnings=(),
                        player_notifications=(),
                        before_results=before_view,
                        after_results=proposed_view,
                        fund_before=draft.original_tournament_fund,
                        fund_after=draft.proposed_tournament_fund,
                    )
                validation_errors = ResultService._validate_game_results(proposed_view)
                if validation_errors:
                    raise ResultValidationError(validation_errors)
                tournament.tournament_fund = draft.proposed_tournament_fund
                await self._apply_result_snapshot(
                    session,
                    tournament,
                    draft,
                    checked_in_by_user_id=superadmin.id,
                )
                await self._recalculate_result_points(session, tournament)
                refreshed = await self._result_service._results_view(session, tournament.id)
                reward_result = await self._apply_reward_reconciliation(
                    session,
                    tournament,
                    refreshed,
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
                    before_results=before_view,
                    after_results=refreshed,
                    fund_before=draft.original_tournament_fund,
                    fund_after=draft.proposed_tournament_fund,
                )
            except Exception:
                await session.rollback()
                raise

    async def _require_closed_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await TournamentRepository(session).get_by_id(tournament_id)
        if tournament is None or tournament.status != TournamentStatus.CLOSED:
            raise ResultTournamentNotFoundError
        return tournament

    async def _results_view_from_snapshot(
        self,
        session: AsyncSession,
        tournament: Tournament,
        snapshot: tuple[TournamentResultSnapshotItemView, ...],
        *,
        tournament_fund: int | None | object = _USE_PERSISTED_TOURNAMENT_FUND,
    ) -> TournamentResultsView:
        effective_fund = (
            tournament.tournament_fund
            if tournament_fund is _USE_PERSISTED_TOURNAMENT_FUND
            else tournament_fund
        )
        players = [
            TournamentResultPlayerView(
                player_id=item.player_id,
                display_name=item.display_name,
                place=item.place,
                knockouts_count=item.knockouts_count,
                big_knockouts_count=item.big_knockouts_count,
                bonus_points=item.bonus_points,
                result_id=item.result_id,
            )
            for item in snapshot
        ]
        knockout_mode, supports_bonus_points = await self._result_service._result_capabilities(
            session,
            tournament,
        )
        view = TournamentResultsView(
            tournament=tournament_view(tournament),
            tournament_fund=effective_fund if isinstance(effective_fund, int) else None,
            players=players,
            photo_count=await self._photo_service.count_for_tournament_in_session(
                session,
                tournament.id,
            ),
            knockout_mode=knockout_mode.value,
            supports_bonus_points=supports_bonus_points,
        )
        return await self._with_recalculated_player_points(
            session,
            tournament,
            view,
            tournament_fund=effective_fund if isinstance(effective_fund, int) else None,
        )

    async def _with_recalculated_player_points(
        self,
        session: AsyncSession,
        tournament: Tournament,
        view: TournamentResultsView,
        *,
        tournament_fund: int | None | object = _USE_PERSISTED_TOURNAMENT_FUND,
    ) -> TournamentResultsView:
        effective_fund = (
            tournament.tournament_fund
            if tournament_fund is _USE_PERSISTED_TOURNAMENT_FUND
            else tournament_fund
        )
        if not isinstance(effective_fund, int):
            return view
        scoring_config, rule = await self._result_service._scoring(session, tournament)
        players = [
            replace(
                player,
                tournament_points=ResultService.calculate_tournament_points(
                    tournament_fund=Decimal(effective_fund),
                    place=player.place,
                    scoring_config=scoring_config,
                    rule=rule,
                ),
                knockout_points=ResultService._knockout_points(
                    knockouts_count=player.knockouts_count,
                    big_knockouts_count=player.big_knockouts_count,
                    scoring_config=scoring_config,
                    rule=rule,
                ),
            )
            for player in view.players
        ]
        return replace(view, players=players)

    async def _validate_draft_current(
        self,
        session: AsyncSession,
        tournament: Tournament,
        draft: ClosedTournamentCorrectionDraftView,
    ) -> None:
        if draft.tournament_id != tournament.id:
            raise ResultTournamentNotFoundError
        if tournament.tournament_fund != draft.original_tournament_fund:
            raise ClosedTournamentCorrectionStaleError
        proposed_player_ids = [item.player_id for item in draft.proposed_results]
        if len(proposed_player_ids) != len(set(proposed_player_ids)):
            raise ResultPlayerAlreadyAddedError
        current = self.snapshot_from_results(
            await self._result_service._results_view(session, tournament.id)
        )
        if current != draft.original_results:
            raise ClosedTournamentCorrectionStaleError

    async def _validate_result_field(
        self,
        session: AsyncSession,
        tournament: Tournament,
        field: ResultField,
        value: int,
    ) -> None:
        knockout_mode, supports_bonus_points = await self._result_service._result_capabilities(
            session,
            tournament,
        )
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

    async def _apply_result_snapshot(
        self,
        session: AsyncSession,
        tournament: Tournament,
        draft: ClosedTournamentCorrectionDraftView,
        *,
        checked_in_by_user_id: int,
    ) -> None:
        repository = TournamentResultRepository(session)
        existing = {
            result.id: result for result in await repository.list_by_tournament(tournament.id)
        }
        original_result_ids = {
            item.result_id for item in draft.original_results if item.result_id is not None
        }
        if set(existing) != original_result_ids:
            raise ClosedTournamentCorrectionStaleError

        proposed_existing_ids = {
            item.result_id for item in draft.proposed_results if item.result_id is not None
        }
        for deleted_result_id in original_result_ids - proposed_existing_ids:
            result = existing[deleted_result_id]
            await self._combination_service.delete_for_player_in_session(
                session,
                tournament_id=tournament.id,
                player_id=result.player_id,
            )
            await repository.delete(result)

        for proposed in draft.proposed_results:
            if proposed.result_id is None:
                await repository.add_check_in(
                    tournament_id=tournament.id,
                    player_id=proposed.player_id,
                    source=TournamentResultSource.WALK_IN_EXISTING,
                    checked_in_at=self.clock.now(),
                    checked_in_by_user_id=checked_in_by_user_id,
                )
                result = await repository.get_by_tournament_and_player(
                    tournament.id,
                    proposed.player_id,
                )
                if result is None:
                    raise ClosedTournamentCorrectionStaleError
            else:
                result = existing.get(proposed.result_id)
                if result is None:
                    raise ClosedTournamentCorrectionStaleError
            result.player_id = proposed.player_id
            result.place = proposed.place
            result.knockouts_count = proposed.knockouts_count
            result.big_knockouts_count = proposed.big_knockouts_count
            result.bonus_points = proposed.bonus_points
        await session.flush()

    async def _preview_reward_reconciliation(
        self,
        session: AsyncSession,
        tournament: Tournament,
        view: TournamentResultsView,
    ) -> PlayerRewardCorrectionResultView:
        return await PlayerRewardService(
            self.session_factory,
            clock=self.clock,
            tournament_day_start_hour=self.tournament_day_start_hour,
        ).preview_prize_stack_bonus_reconciliation_for_closed_tournament(
            session,
            tournament,
            source_results=await self._prize_reward_source_results(session, view),
        )

    async def _apply_reward_reconciliation(
        self,
        session: AsyncSession,
        tournament: Tournament,
        view: TournamentResultsView,
    ) -> PlayerRewardCorrectionResultView:
        return await PlayerRewardService(
            self.session_factory,
            clock=self.clock,
            tournament_day_start_hour=self.tournament_day_start_hour,
        ).reconcile_prize_stack_bonuses_for_closed_tournament(
            session,
            tournament,
            source_results=await self._prize_reward_source_results(session, view),
        )

    async def _prize_reward_source_results(
        self,
        session: AsyncSession,
        view: TournamentResultsView,
    ) -> tuple[PrizeStackBonusSourceResultView, ...]:
        return tuple(
            [
                PrizeStackBonusSourceResultView(
                    player_id=player.player_id,
                    display_name=player.display_name,
                    telegram_id=await self._telegram_id_for_user(session, player.player_id),
                    place=player.place,
                )
                for player in view.players
            ]
        )

    async def _recalculate_result_points(
        self,
        session: AsyncSession,
        tournament: Tournament,
    ) -> None:
        if tournament.tournament_fund is None:
            raise ResultInvalidFundError
        scoring_config, rule = await self._result_service._scoring(session, tournament)
        results = await TournamentResultRepository(session).list_by_tournament(tournament.id)
        for item in results:
            item.tournament_points = ResultService.calculate_tournament_points(
                tournament_fund=Decimal(tournament.tournament_fund),
                place=item.place,
                scoring_config=scoring_config,
                rule=rule,
            )
            item.knockout_points = ResultService._knockout_points(
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
                result_id=player.result_id,
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
                    result_id=(None if item.get("result_id") is None else int(item["result_id"])),
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
                "result_id": item.result_id,
            }
            for item in snapshot
        ]

    @staticmethod
    def correction_draft_from_payload(
        payload: object,
    ) -> ClosedTournamentCorrectionDraftView | None:
        if not isinstance(payload, dict):
            return None
        try:
            tournament_id = int(payload["tournament_id"])
        except (KeyError, TypeError, ValueError):
            return None
        if "original_results" not in payload or "proposed_results" not in payload:
            return None
        original = ClosedTournamentCorrectionService.snapshot_from_payload(
            payload.get("original_results")
        )
        proposed = ClosedTournamentCorrectionService.snapshot_from_payload(
            payload.get("proposed_results")
        )
        return ClosedTournamentCorrectionDraftView(
            tournament_id=tournament_id,
            original_tournament_fund=(
                None
                if payload.get("original_tournament_fund") is None
                else int(payload["original_tournament_fund"])
            ),
            proposed_tournament_fund=(
                None
                if payload.get("proposed_tournament_fund") is None
                else int(payload["proposed_tournament_fund"])
            ),
            original_results=original,
            proposed_results=proposed,
        )

    @staticmethod
    def correction_draft_to_payload(
        draft: ClosedTournamentCorrectionDraftView,
    ) -> dict[str, object]:
        return {
            "tournament_id": draft.tournament_id,
            "original_tournament_fund": draft.original_tournament_fund,
            "proposed_tournament_fund": draft.proposed_tournament_fund,
            "original_results": ClosedTournamentCorrectionService.snapshot_to_payload(
                draft.original_results
            ),
            "proposed_results": ClosedTournamentCorrectionService.snapshot_to_payload(
                draft.proposed_results
            ),
        }

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
                    and ClosedTournamentCorrectionService._snapshot_values(before)
                    == ClosedTournamentCorrectionService._result_values(player)
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
                    ClosedTournamentCorrectionService._field_change(
                        "Место",
                        before.place,
                        player.place,
                    ),
                    ClosedTournamentCorrectionService._field_change(
                        "КО",
                        before.knockouts_count,
                        player.knockouts_count,
                    ),
                    ClosedTournamentCorrectionService._field_change(
                        "БКО",
                        before.big_knockouts_count,
                        player.big_knockouts_count,
                    ),
                    ClosedTournamentCorrectionService._field_change(
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


closed_tournament_correction_service = ClosedTournamentCorrectionService(SessionFactory)
