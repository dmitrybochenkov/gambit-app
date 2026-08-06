import pytest

from app.domain.prize_multiplier_places import (
    PrizeMultiplierPlacesError,
    parse_prize_multiplier_places,
    serialize_prize_multiplier_places,
)


def test_prize_multiplier_places_null_means_disabled() -> None:
    assert parse_prize_multiplier_places(None) == ()
    assert serialize_prize_multiplier_places(None) is None
    assert serialize_prize_multiplier_places([]) is None


def test_prize_multiplier_places_normalizes_sorted_unique_places() -> None:
    assert parse_prize_multiplier_places("[5,1,2]") == (1, 2, 5)
    assert serialize_prize_multiplier_places([5, 1, 2]) == "[1,2,5]"


@pytest.mark.parametrize("value", ["", "{}", '"1,2"', "[0]", "[6]", "[1,1]", "[1.5]", "[true]"])
def test_prize_multiplier_places_rejects_invalid_values(value: str) -> None:
    with pytest.raises(PrizeMultiplierPlacesError):
        parse_prize_multiplier_places(value)
