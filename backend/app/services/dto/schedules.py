from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class TournamentTypeOptionView:
    id: int
    name: str


@dataclass(frozen=True)
class TournamentRebuyView:
    fee: int
    stack: int


@dataclass(frozen=True)
class TournamentTypeDetailView:
    id: int
    name: str
    description: str | None
    entry_fee: int
    entry_stack: int
    addon_fee: int
    addon_stack: int
    rebuys: list[TournamentRebuyView]
    knockout_mode: str


@dataclass(frozen=True)
class TournamentPromptItemView:
    date: date
    tournament_type: TournamentTypeDetailView


@dataclass(frozen=True)
class WeeklyTournamentPlanView:
    week_start: date
    week_end: date
    tournaments: list[TournamentPromptItemView]


@dataclass(frozen=True)
class TournamentPromptDayEditView:
    tournament_date: date
    tournament_types: list[TournamentTypeOptionView]


@dataclass(frozen=True)
class WeeklyScheduleTournamentView:
    id: int
    date: date
    tournament_type_code: str
    tournament_type_name: str
    description: str | None
    entry_fee: int
    entry_stack: int
    addon_fee: int
    addon_stack: int
    rebuys: list[TournamentRebuyView]
    knockout_mode: str
    points_multiplier: Decimal
    prize_place_multiplier: Decimal
    prize_place_multiplier_places: str | None


@dataclass(frozen=True)
class WeeklyScheduleView:
    tournaments: list[WeeklyScheduleTournamentView]
