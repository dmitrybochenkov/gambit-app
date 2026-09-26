import logging
from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.config import settings
from app.db.models import (
    ScoringConfig,
    Tournament,
    TournamentTypeRule,
)
from app.db.models.enums import (
    KnockoutMode,
    TournamentResultSource,
    TournamentStatus,
    UserRole,
)
from app.db.repositories.scoring_config_repository import ScoringConfigRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.repositories.user_repository import UserRepository
from app.db.session import SessionFactory
from app.domain.open_tournament_edit_policy import can_edit_open_tournament_for_actor
from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
)
from app.domain.tournament_close_policy import is_tournament_closeable
from app.domain.tournament_day import resolve_tournament_day
from app.services.access_policy import access_policy
from app.services.dto.results import (
    TournamentCloseReadinessView,
    TournamentResultPlayerView,
    TournamentResultsView,
)
from app.services.dto.tournaments import TournamentView
from app.services.player_reward_service import PlayerRewardService
from app.services.result_errors import (
    ClosedTournamentCorrectionStaleError,
    FutureTournamentCannotBeClosedError,
    ResultCombinationNotFoundError,
    ResultDuplicateNameError,
    ResultInvalidCombinationRankError,
    ResultInvalidFundError,
    ResultInvalidPlayerDataError,
    ResultInvalidTournamentTypeRuleError,
    ResultPlayerAlreadyAddedError,
    ResultPlayerRewardConflictError,
    ResultTodayTournamentInvariantViolationError,
    ResultTodayTournamentNotFoundError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    ResultValidationError,
    TournamentResultsEditingUnavailableError,
)
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField
from app.services.tournament_combination_service import TournamentCombinationService
from app.services.tournament_photo_service import TournamentPhotoService
from app.services.tournament_service import tournament_view

logger = logging.getLogger(__name__)

__all__ = [
    "ClosedTournamentCorrectionStaleError",
    "FutureTournamentCannotBeClosedError",
    "ResultCombinationNotFoundError",
    "ResultDuplicateNameError",
    "ResultInvalidCombinationRankError",
    "ResultInvalidFundError",
    "ResultInvalidPlayerDataError",
    "ResultInvalidTournamentTypeRuleError",
    "ResultPlayerAlreadyAddedError",
    "ResultPlayerRewardConflictError",
    "ResultService",
    "ResultTodayTournamentInvariantViolationError",
    "ResultTodayTournamentNotFoundError",
    "ResultTournamentNotFoundError",
    "ResultUserNotFoundError",
    "ResultValidationError",
    "TournamentResultsEditingUnavailableError",
    "result_service",
]

_USE_PERSISTED_TOURNAMENT_FUND = object()


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

    async def list_editable_tournaments(
        self,
        admin_telegram_id: int,
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            business_date = self._tournament_day()
            repository = TournamentRepository(session)
            if actor.role == UserRole.SUPERADMIN:
                tournaments = await repository.list_active_on_or_before(business_date)
            else:
                tournaments = await repository.list_active_on_date(business_date)
            return [tournament_view(tournament) for tournament in tournaments]

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

    async def get_tournament_results(
        self,
        admin_telegram_id: int,
        tournament_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
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
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            await self._update_result_field(
                session=session,
                tournament=tournament,
                player_id=player_id,
                field=field,
                value=value,
            )
            await session.commit()
            return await self._results_view(session, tournament.id)

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
                    tournament_points=self.calculate_tournament_points(
                        tournament_fund=Decimal(fund),
                        place=player.place,
                        scoring_config=scoring_config,
                        rule=rule,
                    ),
                    knockout_points=self.calculate_knockout_points(
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
                item.tournament_points = self.calculate_tournament_points(
                    tournament_fund=Decimal(fund),
                    place=item.place,
                    scoring_config=scoring_config,
                    rule=rule,
                )
                item.knockout_points = self.calculate_knockout_points(
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
            actor = await access_policy.require_admin(session, admin_telegram_id)
            tournament = await self._require_editable_tournament_for_actor(
                session,
                tournament_id,
                actor_role=actor.role,
            )
            view = await self._results_view(session, tournament.id)
            return self.validate_game_results(view)

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

    async def _readiness_view(
        self,
        session: AsyncSession,
        tournament: Tournament,
        *,
        view: TournamentResultsView | None = None,
    ) -> TournamentCloseReadinessView:
        results = view or await self._results_view(session, tournament.id)
        validation_errors = self.validate_game_results(results)
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
            players_count=len(results.players),
            photo_count=results.photo_count,
            has_photos=has_photos,
            has_checkins=has_checkins,
            validation_errors=validation_errors,
            reasons=reasons,
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

    @staticmethod
    def validate_game_results(results: TournamentResultsView) -> list[str]:
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
            results.knockout_mode
            in {
                KnockoutMode.SMALL_BIG.value,
                KnockoutMode.MAIN_KO.value,
            }
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
        scoring_config = await ScoringConfigRepository(session).get_by_id(
            tournament.scoring_config_id
        )
        if scoring_config is None:
            raise ResultTournamentNotFoundError
        return scoring_config, await TournamentTypeRepository(session).get_rule(
            tournament.tournament_type_id
        )

    @staticmethod
    def calculate_tournament_points(
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
    def calculate_knockout_points(
        knockouts_count: int,
        big_knockouts_count: int,
        scoring_config: ScoringConfig,
        rule: TournamentTypeRule | None,
    ) -> Decimal:
        if rule is None or rule.knockout_mode == KnockoutMode.NONE:
            return Decimal("0")
        if rule.knockout_mode == KnockoutMode.SMALL:
            points = knockouts_count * scoring_config.knockout_small_points
        elif rule.knockout_mode == KnockoutMode.SMALL_BIG:
            points = (
                knockouts_count * scoring_config.knockout_small_points
                + big_knockouts_count * scoring_config.knockout_big_points
            )
        elif rule.knockout_mode == KnockoutMode.MAIN_KO:
            if (
                scoring_config.knockout_main_points is None
                or scoring_config.knockout_main_final_points is None
            ):
                raise ResultInvalidTournamentTypeRuleError
            points = (
                knockouts_count * scoring_config.knockout_main_points
                + big_knockouts_count * scoring_config.knockout_main_final_points
            )
        else:
            raise ResultInvalidTournamentTypeRuleError
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
