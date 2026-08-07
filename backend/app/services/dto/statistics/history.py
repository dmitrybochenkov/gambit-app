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
    tournament_name: str


@dataclass(frozen=True)
class HistoricalTournamentResultRowView:
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    total_points: Decimal

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


@dataclass(frozen=True)
class HistoricalTournamentResultView:
    tournament: HistoricalTournamentView
    rows: list[HistoricalTournamentResultRowView]
