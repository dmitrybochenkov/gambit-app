from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.dto.schedules import TournamentRebuyView


@dataclass(frozen=True)
class TournamentView:
    id: int
    date: date
    tournament_type_id: int
    tournament_type_name: str | None
    tournament_type_code: str | None = None


@dataclass(frozen=True)
class TournamentEconomyView:
    entry_fee: int
    entry_stack: int
    addon_fee: int
    addon_stack: int
    rebuys: list[TournamentRebuyView]


@dataclass(frozen=True)
class TournamentRulesView:
    points_multiplier: Decimal
    prize_place_multiplier: Decimal
    prize_place_multiplier_places: str | None
    knockout_mode: str
    supports_bonus_points: bool


@dataclass(frozen=True)
class TournamentScheduleDetailsView:
    id: int
    date: date
    tournament_type_name: str
    description: str | None
    economy: TournamentEconomyView | None
    rules: TournamentRulesView | None


@dataclass(frozen=True)
class SuperadminTournamentHubView:
    open_tournaments_count: int
