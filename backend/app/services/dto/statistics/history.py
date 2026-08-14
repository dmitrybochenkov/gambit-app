from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class HistoryYearView:
    year: int


@dataclass(frozen=True)
class HistoryMonthView:
    year: int
    month: int
    label: str


@dataclass(frozen=True)
class HistoricalTournamentView:
    id: int
    date: date
    display_name: str


@dataclass(frozen=True)
class HistoricalTournamentResultRowView:
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    total_points: Decimal
    bonus_points: int = 0

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


@dataclass(frozen=True)
class HistoricalTournamentResultView:
    tournament: HistoricalTournamentView
    rows: list[HistoricalTournamentResultRowView]

    @property
    def has_knockouts(self) -> bool:
        return any(row.knockouts_count > 0 for row in self.rows)

    @property
    def has_big_knockouts(self) -> bool:
        return any(row.big_knockouts_count > 0 for row in self.rows)

    @property
    def has_bonus_points(self) -> bool:
        return any(row.bonus_points > 0 for row in self.rows)
