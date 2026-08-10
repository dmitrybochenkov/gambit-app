import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.clock import Clock, club_clock
from app.db.models import (
    ScoringConfig,
    Tournament,
    TournamentTypeRule,
)
from app.db.models.enums import (
    KnockoutMode,
    TournamentStatus,
)
from app.db.repositories.scoring_config_repository import ScoringConfigRepository
from app.db.repositories.season_repository import SeasonRepository
from app.db.repositories.tournament_repository import TournamentRepository
from app.db.repositories.tournament_result_repository import TournamentResultRepository
from app.db.repositories.tournament_type_repository import TournamentTypeRepository
from app.db.session import SessionFactory
from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
)
from app.domain.tournament_close_policy import is_tournament_closeable
from app.domain.tournament_result_edit_policy import is_tournament_result_editable
from app.services.access_policy import access_policy
from app.services.dto.results import TournamentResultPlayerView, TournamentResultsView
from app.services.dto.tournaments import TournamentView
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField
from app.services.tournament_service import tournament_view

logger = logging.getLogger(__name__)


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


class ResultService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = club_clock,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def get_today_tournament_results(
        self,
        admin_telegram_id: int,
    ) -> TournamentResultsView:
        async with self.session_factory() as session:
            await access_policy.require_admin(session, admin_telegram_id)
            business_date = self.clock.today()
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
    ) -> list[TournamentView]:
        async with self.session_factory() as session:
            await access_policy.require_superadmin(session, superadmin_telegram_id)
            business_date = self.clock.today()
            tournaments = await TournamentRepository(session).list_active_on_or_before(
                business_date
            )
            return [tournament_view(tournament) for tournament in tournaments]

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
            result = await TournamentResultRepository(session).get_by_tournament_and_player(
                tournament.id, player_id
            )
            if result is None:
                raise ResultUserNotFoundError

            knockout_mode, supports_bonus_points = await self._result_capabilities(
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

            if field == ResultField.PLACE:
                occupied = await TournamentResultRepository(session).list_by_tournament_and_place(
                    tournament.id,
                    value,
                    exclude_result_id=result.id,
                )
                if occupied:
                    raise ResultInvalidPlayerDataError
                result.place = value
            elif field == ResultField.KNOCKOUTS:
                result.knockouts_count = value
            elif field == ResultField.BIG_KNOCKOUTS:
                result.big_knockouts_count = value
            elif field == ResultField.BONUS:
                result.bonus_points = value

            await session.commit()
            return await self._results_view(session, tournament.id)

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
            errors = self._validate_game_results(view)
            if errors:
                raise ResultValidationError(errors)

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
            await session.commit()
            return await self._results_view(session, tournament.id)

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
            return self._validate_game_results(view)

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
        if not is_tournament_result_editable(tournament, self.clock.today()):
            raise TournamentResultsEditingUnavailableError
        return tournament

    async def _require_closeable_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Tournament:
        tournament = await self._require_active_tournament(session, tournament_id)
        if not is_tournament_closeable(tournament, self.clock.today()):
            raise FutureTournamentCannotBeClosedError
        return tournament

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
            knockout_mode=knockout_mode.value,
            supports_bonus_points=supports_bonus_points,
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
