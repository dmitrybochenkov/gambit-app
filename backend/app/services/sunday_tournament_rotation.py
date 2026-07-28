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


class SundayTournamentRotationCodeError(ValueError):
    pass


@dataclass(frozen=True)
class SundayTournamentRotation:
    anchor: date = SUNDAY_ROTATION_ANCHOR
    rotation_codes: tuple[str, ...] = SUNDAY_ROTATION_CODES

    def code_for(self, target_date: date) -> str:
        return self.fallback_code_for(target_date)

    def fallback_code_for(self, target_date: date) -> str:
        if target_date.weekday() != SUNDAY_WEEKDAY:
            raise SundayTournamentRotationDateError
        weeks = (target_date - self.anchor).days // 7
        return self.rotation_codes[weeks % len(self.rotation_codes)]

    def next_code_after(self, previous_code: str) -> str:
        try:
            previous_index = self.rotation_codes.index(previous_code)
        except ValueError as error:
            raise SundayTournamentRotationCodeError(previous_code) from error
        return self.rotation_codes[(previous_index + 1) % len(self.rotation_codes)]


sunday_tournament_rotation = SundayTournamentRotation()
