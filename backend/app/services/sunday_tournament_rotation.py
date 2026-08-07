from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SUNDAY_WEEKDAY = 6

SUNDAY_ROTATION_ANCHOR = date(2026, 7, 26)


class SundayTournamentRotationDateError(ValueError):
    pass


class SundayTournamentRotationCodeError(ValueError):
    pass


@dataclass(frozen=True)
class SundayTournamentRotation:
    anchor: date = SUNDAY_ROTATION_ANCHOR

    def code_for(self, target_date: date, rotation_codes: tuple[str, ...]) -> str:
        return self.fallback_code_for(target_date, rotation_codes)

    def fallback_code_for(self, target_date: date, rotation_codes: tuple[str, ...]) -> str:
        if target_date.weekday() != SUNDAY_WEEKDAY:
            raise SundayTournamentRotationDateError
        if not rotation_codes:
            raise SundayTournamentRotationCodeError("empty rotation")
        weeks = (target_date - self.anchor).days // 7
        return rotation_codes[weeks % len(rotation_codes)]

    def next_code_after(self, previous_code: str, rotation_codes: tuple[str, ...]) -> str:
        if not rotation_codes:
            raise SundayTournamentRotationCodeError("empty rotation")
        try:
            previous_index = rotation_codes.index(previous_code)
        except ValueError as error:
            raise SundayTournamentRotationCodeError(previous_code) from error
        return rotation_codes[(previous_index + 1) % len(rotation_codes)]


sunday_tournament_rotation = SundayTournamentRotation()
