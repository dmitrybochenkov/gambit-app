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
    tournament_type_calendar_code: str | None = None
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
    tournament_type_code: str | None = None


@dataclass(frozen=True)
class PlayerTournamentView:
    id: int
    date: date
    tournament_type_code: str | None
    tournament_type_name: str
    description: str | None
    registration_open: bool
    is_registered: bool
    can_register: bool
    can_cancel_registration: bool
    my_registration_status: str
    economy: TournamentEconomyView | None = None
    rules: TournamentRulesView | None = None


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
    tournament_types: tuple["TournamentCalendarMonthTypeView", ...] = ()


@dataclass(frozen=True)
class TournamentCalendarMonthTypeView:
    id: int
    name: str
    short_name: str
    calendar_code: str


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
    calendar_code: str | None = None

    @property
    def display_name(self) -> str:
        return tournament_type_display_name(self.code, self.name)


@dataclass(frozen=True)
class WeeklyTemplateTypeView:
    id: int
    code: str
    name: str
    calendar_code: str
    is_creatable: bool


@dataclass(frozen=True)
class WeeklyTemplateDayView:
    weekday: int
    tournament_types: tuple[WeeklyTemplateTypeView, ...]


@dataclass(frozen=True)
class WeeklyTemplateView:
    days: tuple[WeeklyTemplateDayView, ...]


@dataclass(frozen=True)
class TournamentFormatView:
    id: int
    code: str
    name: str
    calendar_code: str
    is_creatable: bool
    description: str | None = None
    economy: TournamentEconomyView | None = None
    rules: TournamentRulesView | None = None

    @property
    def display_name(self) -> str:
        return tournament_type_display_name(self.code, self.name)


def tournament_type_display_name(code: str, name: str) -> str:
    versioned_names = {
        "bounty_v2": "Bounty v2",
        "classic": "Классика",
        "classic_v2": "Классика 2",
        "classic_v3": "Классика 3",
        "freezeout_v2": "Freezeout v2",
    }
    return versioned_names.get(code, name)


@dataclass(frozen=True)
class TournamentFormatAvailabilityResultView:
    tournament_format: TournamentFormatView
    affected_weekdays: tuple[int, ...]


@dataclass(frozen=True)
class TournamentCalendarFormatDetailView:
    id: int
    name: str
    description: str | None
    economy: TournamentEconomyView | None
    rules: TournamentRulesView | None
    code: str = ""
    calendar_code: str = "?"
    is_creatable: bool = False


@dataclass(frozen=True)
class TournamentCalendarTournamentDetailView:
    tournament: TournamentView
    description: str | None
    economy: TournamentEconomyView | None
    rules: TournamentRulesView | None
    knockout_small_points: int
    knockout_big_points: int
    knockout_main_points: int | None
    knockout_main_final_points: int | None


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
class TournamentCalendarDraftItem:
    tournament_date: date
    tournament_type_id: int


@dataclass(frozen=True)
class TournamentCalendarDraftCommand:
    year: int
    month: int
    row_number: int
    tournaments: tuple[TournamentCalendarDraftItem, ...]


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
    user_id: int
    tournament: TournamentView
