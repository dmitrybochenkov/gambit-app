from datetime import date

import pytest

from app.services.sunday_tournament_rotation import (
    SUNDAY_ROTATION_ANCHOR,
    SundayTournamentRotation,
    SundayTournamentRotationCodeError,
    SundayTournamentRotationDateError,
)

ROTATION_CODES = ("mystery_bounty", "boss_bounty")


def test_anchor_sunday_selects_first_rotation_item() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(SUNDAY_ROTATION_ANCHOR, ROTATION_CODES) == "mystery_bounty"


def test_next_sunday_selects_second_rotation_item() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(date(2026, 8, 2), ROTATION_CODES) == "boss_bounty"


def test_third_sunday_wraps_to_first_rotation_item() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(date(2026, 8, 9), ROTATION_CODES) == "mystery_bounty"


def test_later_sunday_remains_deterministic() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(date(2026, 10, 4), ROTATION_CODES) == "mystery_bounty"


def test_sundays_before_anchor_rotate_correctly() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.code_for(date(2026, 7, 19), ROTATION_CODES) == "boss_bounty"
    assert rotation.code_for(date(2026, 7, 12), ROTATION_CODES) == "mystery_bounty"


def test_non_sunday_is_rejected() -> None:
    rotation = SundayTournamentRotation()

    with pytest.raises(SundayTournamentRotationDateError):
        rotation.code_for(date(2026, 7, 27), ROTATION_CODES)


def test_repeated_calls_for_same_date_return_same_result() -> None:
    rotation = SundayTournamentRotation()

    first = rotation.code_for(date(2026, 8, 2), ROTATION_CODES)
    second = rotation.code_for(date(2026, 8, 2), ROTATION_CODES)

    assert first == second == "boss_bounty"


def test_next_code_after_advances_rotation_order() -> None:
    rotation = SundayTournamentRotation()

    assert rotation.next_code_after("mystery_bounty", ROTATION_CODES) == "boss_bounty"
    assert rotation.next_code_after("boss_bounty", ROTATION_CODES) == "mystery_bounty"


def test_next_code_after_rejects_unknown_code() -> None:
    rotation = SundayTournamentRotation()

    with pytest.raises(SundayTournamentRotationCodeError):
        rotation.next_code_after("classic", ROTATION_CODES)
