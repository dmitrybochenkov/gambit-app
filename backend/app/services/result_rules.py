from decimal import ROUND_HALF_UP, Decimal

from app.db.models import ScoringConfig, TournamentTypeRule
from app.db.models.enums import KnockoutMode
from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
)
from app.services.dto.results import TournamentResultPlayerView, TournamentResultsView
from app.services.result_errors import (
    ResultInvalidFundError,
    ResultInvalidTournamentTypeRuleError,
)
from app.services.result_field_policy import is_result_field_allowed
from app.services.result_fields import ResultField


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
        errors.append("Дублируются места: " + ", ".join(str(place) for place in duplicates) + ".")
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


def validate_tournament_fund(value: int | Decimal) -> int:
    try:
        fund = Decimal(value)
    except Exception as exc:
        raise ResultInvalidFundError from exc
    if fund != fund.to_integral_value() or fund <= 0 or fund % Decimal("10") != 0:
        raise ResultInvalidFundError
    return int(fund)


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


def find_result_player(
    results: TournamentResultsView,
    player_id: int,
) -> TournamentResultPlayerView | None:
    return next((player for player in results.players if player.player_id == player_id), None)


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


def editable_result_fields(results: TournamentResultsView) -> list[ResultField]:
    return [
        field
        for field in (
            ResultField.PLACE,
            ResultField.KNOCKOUTS,
            ResultField.BIG_KNOCKOUTS,
            ResultField.BONUS,
        )
        if result_field_is_allowed(
            results.knockout_mode,
            field,
            results.supports_bonus_points,
        )
    ]


def occupied_result_places(results: TournamentResultsView) -> set[int]:
    return {player.place for player in results.players if player.place is not None}
