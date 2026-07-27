from datetime import date

import pytest

from app.services.sunday_tournament_rotation import (
    SUNDAY_ROTATION_ANCHOR,
    SundayTournamentRotation,
    SundayTournamentRotationDateError,
)


def test_anchor_sunday_selects_first_rotation_item() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(SUNDAY_ROTATION_ANCHOR) == "mystery_bounty"


def test_next_sunday_selects_second_rotation_item() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(date(2026, 8, 2)) == "boss_bounty"


def test_third_sunday_wraps_to_first_rotation_item() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(date(2026, 8, 9)) == "mystery_bounty"


def test_later_sunday_remains_deterministic() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(date(2026, 10, 4)) == "mystery_bounty"


def test_sundays_before_anchor_rotate_correctly() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(date(2026, 7, 19)) == "boss_bounty"
    assert rotation.code_for(date(2026, 7, 12)) == "mystery_bounty"


def test_non_sunday_is_rejected() -> None:
    rotation = SundayTournamentRotation()

    with pytest.raises(SundayTournamentRotationDateError):
        rotation.code_for(date(2026, 7, 27))


def test_repeated_calls_for_same_date_return_same_result() -> None:
    rotation = SundayTournamentRotation()

    first = rotation.code_for(date(2026, 8, 2))
    second = rotation.code_for(date(2026, 8, 2))

    assert first == second == "boss_bounty"
