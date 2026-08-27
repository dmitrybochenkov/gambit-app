from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.dto.schedules import TournamentRebuyView
from app.services.pagination import Page


@dataclass(frozen=True)
class TournamentView:
    id: int
    date: date
    tournament_type_id: int
    tournament_type_name: str | None
    tournament_type_code: str | None = None
    registration_open: bool = True


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


@dataclass(frozen=True)
class SuperadminOpenTournamentListItemView:
    tournament: TournamentView


SuperadminOpenTournamentPageView = Page[SuperadminOpenTournamentListItemView]


@dataclass(frozen=True)
class TournamentCalendarDayView:
    date: date
    in_month: bool
    tournament: TournamentView | None
    registrations_count: int = 0
    editable_future: bool = False


@dataclass(frozen=True)
class TournamentCalendarWeekView:
    row_number: int
    days: tuple[TournamentCalendarDayView, ...]


@dataclass(frozen=True)
class TournamentCalendarMonthView:
    year: int
    month: int
    weeks: tuple[TournamentCalendarWeekView, ...]


@dataclass(frozen=True)
class TournamentCalendarWeekDetailView:
    year: int
    month: int
    row_number: int
    week_start: date
    week_end: date
    days: tuple[TournamentCalendarDayView, ...]
    has_tournaments: bool
    has_unapproved_tournaments: bool
    is_empty: bool


@dataclass(frozen=True)
class TournamentCalendarTypeOptionView:
    id: int
    code: str
    name: str


@dataclass(frozen=True)
class TournamentCalendarCreatePreviewView:
    tournament_date: date
    tournament_type: TournamentCalendarTypeOptionView


@dataclass(frozen=True)
class TournamentCalendarAutofillPreviewView:
    week_start: date
    week_end: date
    tournaments: tuple[TournamentCalendarCreatePreviewView, ...]


@dataclass(frozen=True)
class TournamentCalendarApprovalPreviewView:
    week_start: date
    week_end: date
    tournaments: tuple[TournamentView, ...]


@dataclass(frozen=True)
class TournamentCalendarTypeChangePreviewView:
    tournament: TournamentView
    new_type: TournamentCalendarTypeOptionView


@dataclass(frozen=True)
class TournamentCalendarDeletePreviewView:
    tournament: TournamentView
    registrations_count: int


@dataclass(frozen=True)
class TournamentCancellationNotificationView:
    telegram_id: int
    tournament: TournamentView
