from datetime import date
from decimal import Decimal

import pytest

from app.db.models import ScoringConfig, TournamentTypeRule
from app.db.models.enums import KnockoutMode
from app.services.dto.results import TournamentResultPlayerView, TournamentResultsView
from app.services.dto.tournaments import TournamentView
from app.services.result_errors import ResultInvalidFundError
from app.services.result_fields import ResultField
from app.services.result_rules import (
    calculate_knockout_points,
    calculate_tournament_points,
    editable_result_fields,
    find_result_player,
    occupied_result_places,
    result_field_is_allowed,
    validate_game_results,
    validate_tournament_fund,
)


def _results_view(
    *,
    players: list[TournamentResultPlayerView],
    knockout_mode: str = KnockoutMode.NONE.value,
    supports_bonus_points: bool = False,
) -> TournamentResultsView:
    return TournamentResultsView(
        tournament=TournamentView(
            id=1,
            date=date(2026, 9, 27),
            tournament_type_id=1,
            tournament_type_name="Test",
        ),
        tournament_fund=None,
        players=players,
        knockout_mode=knockout_mode,
        supports_bonus_points=supports_bonus_points,
    )


def _player(player_id: int, place: int | None = None) -> TournamentResultPlayerView:
    return TournamentResultPlayerView(
        player_id=player_id,
        display_name=f"Player {player_id}",
        place=place,
        knockouts_count=0,
        big_knockouts_count=0,
    )


def test_result_validation_and_view_rules_preserve_contract() -> None:
    players = [_player(1, 1), _player(2, 1)]
    results = _results_view(
        players=players,
        knockout_mode=KnockoutMode.SMALL_BIG.value,
        supports_bonus_points=True,
    )

    assert validate_game_results(results) == [
        "Введи места: 2.",
        "Дублируются места: 1.",
        "Введи хотя бы один 🥊 или 👑🥊.",
    ]
    assert find_result_player(results, 2) is players[1]
    assert find_result_player(results, 3) is None
    assert occupied_result_places(results) == {1}
    assert editable_result_fields(results) == [
        ResultField.PLACE,
        ResultField.KNOCKOUTS,
        ResultField.BIG_KNOCKOUTS,
        ResultField.BONUS,
    ]
    assert result_field_is_allowed(
        KnockoutMode.SMALL_BIG.value,
        ResultField.BIG_KNOCKOUTS,
    )


def test_result_scoring_rules_preserve_bound_configuration() -> None:
    scoring = ScoringConfig(
        place_1_coefficient=Decimal("0.40"),
        knockout_small_points=20,
        knockout_big_points=75,
    )
    rule = TournamentTypeRule(
        tournament_type_id=1,
        points_multiplier=Decimal("1.5"),
        prize_place_multiplier=Decimal("2"),
        prize_place_multiplier_places="[1]",
        knockout_mode=KnockoutMode.SMALL_BIG,
    )

    assert calculate_tournament_points(Decimal("1000"), 1, scoring, rule) == Decimal("1200.00")
    assert calculate_knockout_points(2, 1, scoring, rule) == Decimal("115.00")


@pytest.mark.parametrize("value", [None, 0, -10, 105, Decimal("10.5")])
def test_tournament_fund_validation_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ResultInvalidFundError):
        validate_tournament_fund(value)  # type: ignore[arg-type]


def test_tournament_fund_validation_accepts_valid_value() -> None:
    assert validate_tournament_fund(1000) == 1000
