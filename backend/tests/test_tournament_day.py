from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.common.clock import FixedClock
from app.domain.tournament_day import resolve_tournament_day


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 8, 16, 0, 0, tzinfo=ZoneInfo("Europe/Moscow")), "2026-08-15"),
        (datetime(2026, 8, 16, 5, 0, tzinfo=ZoneInfo("Europe/Moscow")), "2026-08-15"),
        (datetime(2026, 8, 16, 10, 59, tzinfo=ZoneInfo("Europe/Moscow")), "2026-08-15"),
        (datetime(2026, 8, 16, 11, 0, tzinfo=ZoneInfo("Europe/Moscow")), "2026-08-16"),
        (datetime(2026, 8, 16, 23, 59, tzinfo=ZoneInfo("Europe/Moscow")), "2026-08-16"),
    ],
)
def test_resolve_tournament_day_boundaries(value: datetime, expected: str) -> None:
    assert resolve_tournament_day(FixedClock(value), start_hour=11).isoformat() == expected
