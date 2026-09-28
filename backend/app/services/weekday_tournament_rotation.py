from __future__ import annotations

from dataclasses import dataclass
from datetime import date

ROTATION_ANCHOR = date(2026, 7, 26)


class WeekdayTournamentRotationCodeError(ValueError):
    pass


@dataclass(frozen=True)
class WeekdayTournamentRotation:
    anchor: date = ROTATION_ANCHOR

    def fallback_code_for(self, target_date: date, rotation_codes: tuple[str, ...]) -> str:
        if not rotation_codes:
            raise WeekdayTournamentRotationCodeError("empty rotation")
        weeks = (target_date - self.anchor).days // 7
        return rotation_codes[weeks % len(rotation_codes)]

    def next_code_after(self, previous_code: str, rotation_codes: tuple[str, ...]) -> str:
        if not rotation_codes:
            raise WeekdayTournamentRotationCodeError("empty rotation")
        try:
            previous_index = rotation_codes.index(previous_code)
        except ValueError as error:
            raise WeekdayTournamentRotationCodeError(previous_code) from error
        return rotation_codes[(previous_index + 1) % len(rotation_codes)]


weekday_tournament_rotation = WeekdayTournamentRotation()
