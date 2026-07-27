from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SUNDAY_WEEKDAY = 6

# Temporary explicit anchor: repository data has rotation order, but no historical
# anchor date. Product examples use 2026-07-26 as Mystery Bounty and 2026-08-02
# as Boss Bounty.
SUNDAY_ROTATION_ANCHOR = date(2026, 7, 26)
SUNDAY_ROTATION_CODES = ("mystery_bounty", "boss_bounty")


class SundayTournamentRotationDateError(ValueError):
    pass


@dataclass(frozen=True)
class SundayTournamentRotation:
    anchor: date = SUNDAY_ROTATION_ANCHOR
    rotation_codes: tuple[str, ...] = SUNDAY_ROTATION_CODES

    def code_for(self, target_date: date) -> str:
        if target_date.weekday() != SUNDAY_WEEKDAY:
            raise SundayTournamentRotationDateError
        weeks = (target_date - self.anchor).days // 7
        return self.rotation_codes[weeks % len(self.rotation_codes)]


sunday_tournament_rotation = SundayTournamentRotation()
