from datetime import date

import pytest

from app.services.weekday_tournament_rotation import (
    ROTATION_ANCHOR,
    WeekdayTournamentRotation,
    WeekdayTournamentRotationCodeError,
)

ROTATION_CODES = ("mystery_bounty", "boss_bounty")


@pytest.mark.parametrize(
    ("target_date", "expected"),
    [
        (ROTATION_ANCHOR, "mystery_bounty"),
        (date(2026, 8, 2), "boss_bounty"),
        (date(2026, 8, 9), "mystery_bounty"),
        (date(2026, 7, 19), "boss_bounty"),
        (date(2026, 7, 12), "mystery_bounty"),
        (date(2026, 7, 29), "mystery_bounty"),
        (date(2026, 8, 5), "boss_bounty"),
    ],
)
def test_fallback_rotation_is_deterministic_for_any_weekday(
    target_date: date,
    expected: str,
) -> None:
    rotation = WeekdayTournamentRotation()

    assert rotation.fallback_code_for(target_date, ROTATION_CODES) == expected


def test_next_code_after_advances_and_wraps() -> None:
    rotation = WeekdayTournamentRotation()

    assert rotation.next_code_after("mystery_bounty", ROTATION_CODES) == "boss_bounty"
    assert rotation.next_code_after("boss_bounty", ROTATION_CODES) == "mystery_bounty"


def test_next_code_after_rejects_unknown_code() -> None:
    with pytest.raises(WeekdayTournamentRotationCodeError):
        WeekdayTournamentRotation().next_code_after("classic", ROTATION_CODES)
