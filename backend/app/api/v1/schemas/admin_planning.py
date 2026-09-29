from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.services.dto.tournaments import (
    TournamentCalendarApprovalPreviewView,
    TournamentCalendarAutofillPreviewView,
    TournamentCalendarCreatePreviewView,
    TournamentCalendarDayView,
    TournamentCalendarDeletePreviewView,
    TournamentCalendarFormatDetailView,
    TournamentCalendarMonthView,
    TournamentCalendarTypeChangePreviewView,
    TournamentCalendarTypeOptionView,
    TournamentCalendarWeekDetailView,
    TournamentEconomyView,
    TournamentRulesView,
    TournamentView,
)


class PlanningTournamentResponse(BaseModel):
    id: int
    date: date
    tournament_type_id: int
    tournament_type_name: str | None
    tournament_type_code: str | None
    tournament_type_calendar_code: str | None
    registration_open: bool

    @classmethod
    def from_view(cls, view: TournamentView) -> "PlanningTournamentResponse":
        return cls(**view.__dict__)


class PlanningTournamentTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    calendar_code: str | None

    @classmethod
    def from_view(
        cls,
        view: TournamentCalendarTypeOptionView,
    ) -> "PlanningTournamentTypeResponse":
        return cls(**view.__dict__)


class PlanningCalendarDayResponse(BaseModel):
    date: date
    in_month: bool
    tournament: PlanningTournamentResponse | None
    registrations_count: int
    editable_future: bool

    @classmethod
    def from_view(cls, view: TournamentCalendarDayView) -> "PlanningCalendarDayResponse":
        return cls(
            date=view.date,
            in_month=view.in_month,
            tournament=(
                PlanningTournamentResponse.from_view(view.tournament)
                if view.tournament is not None
                else None
            ),
            registrations_count=view.registrations_count,
            editable_future=view.editable_future,
        )


class PlanningCalendarWeekResponse(BaseModel):
    row_number: int
    days: list[PlanningCalendarDayResponse]


class PlanningCalendarMonthTypeResponse(BaseModel):
    id: int
    name: str
    short_name: str
    calendar_code: str


class PlanningCalendarMonthResponse(BaseModel):
    year: int
    month: int
    weeks: list[PlanningCalendarWeekResponse]
    tournament_types: list[PlanningCalendarMonthTypeResponse]

    @classmethod
    def from_view(cls, view: TournamentCalendarMonthView) -> "PlanningCalendarMonthResponse":
        return cls(
            year=view.year,
            month=view.month,
            weeks=[
                PlanningCalendarWeekResponse(
                    row_number=week.row_number,
                    days=[PlanningCalendarDayResponse.from_view(day) for day in week.days],
                )
                for week in view.weeks
            ],
            tournament_types=[
                PlanningCalendarMonthTypeResponse(**item.__dict__) for item in view.tournament_types
            ],
        )


class PlanningCalendarWeekDetailResponse(BaseModel):
    year: int
    month: int
    row_number: int
    week_start: date
    week_end: date
    days: list[PlanningCalendarDayResponse]
    has_tournaments: bool
    has_unapproved_tournaments: bool
    is_empty: bool

    @classmethod
    def from_view(
        cls,
        view: TournamentCalendarWeekDetailView,
    ) -> "PlanningCalendarWeekDetailResponse":
        return cls(
            year=view.year,
            month=view.month,
            row_number=view.row_number,
            week_start=view.week_start,
            week_end=view.week_end,
            days=[PlanningCalendarDayResponse.from_view(day) for day in view.days],
            has_tournaments=view.has_tournaments,
            has_unapproved_tournaments=view.has_unapproved_tournaments,
            is_empty=view.is_empty,
        )


class PlanningRebuyResponse(BaseModel):
    fee: int
    stack: int


class PlanningEconomyResponse(BaseModel):
    entry_fee: int
    entry_stack: int
    addon_fee: int
    addon_stack: int
    rebuys: list[PlanningRebuyResponse]

    @classmethod
    def from_view(cls, view: TournamentEconomyView) -> "PlanningEconomyResponse":
        return cls(
            entry_fee=view.entry_fee,
            entry_stack=view.entry_stack,
            addon_fee=view.addon_fee,
            addon_stack=view.addon_stack,
            rebuys=[PlanningRebuyResponse(**item.__dict__) for item in view.rebuys],
        )


class PlanningRulesResponse(BaseModel):
    points_multiplier: Decimal
    prize_place_multiplier: Decimal
    prize_place_multiplier_places: str | None
    knockout_mode: str
    supports_bonus_points: bool

    @classmethod
    def from_view(cls, view: TournamentRulesView) -> "PlanningRulesResponse":
        return cls(**view.__dict__)


class PlanningFormatDetailResponse(BaseModel):
    id: int
    name: str
    description: str | None
    economy: PlanningEconomyResponse | None
    rules: PlanningRulesResponse | None

    @classmethod
    def from_view(
        cls,
        view: TournamentCalendarFormatDetailView,
    ) -> "PlanningFormatDetailResponse":
        return cls(
            id=view.id,
            name=view.name,
            description=view.description,
            economy=(
                PlanningEconomyResponse.from_view(view.economy)
                if view.economy is not None
                else None
            ),
            rules=(PlanningRulesResponse.from_view(view.rules) if view.rules is not None else None),
        )


class PlanningTournamentCommand(BaseModel):
    tournament_date: date
    tournament_type_id: int


class PlanningCreatePreviewResponse(BaseModel):
    tournament_date: date
    tournament_type: PlanningTournamentTypeResponse

    @classmethod
    def from_view(
        cls, view: TournamentCalendarCreatePreviewView
    ) -> "PlanningCreatePreviewResponse":
        return cls(
            tournament_date=view.tournament_date,
            tournament_type=PlanningTournamentTypeResponse.from_view(view.tournament_type),
        )


class PlanningWeekCommand(BaseModel):
    year: int
    month: int
    row_number: int


class PlanningAutofillResponse(BaseModel):
    week_start: date
    week_end: date
    tournaments: list[PlanningCreatePreviewResponse]

    @classmethod
    def from_view(
        cls,
        view: TournamentCalendarAutofillPreviewView,
    ) -> "PlanningAutofillResponse":
        return cls(
            week_start=view.week_start,
            week_end=view.week_end,
            tournaments=[
                PlanningCreatePreviewResponse.from_view(item) for item in view.tournaments
            ],
        )


class PlanningApprovalResponse(BaseModel):
    week_start: date
    week_end: date
    tournaments: list[PlanningTournamentResponse]

    @classmethod
    def from_view(
        cls,
        view: TournamentCalendarApprovalPreviewView,
    ) -> "PlanningApprovalResponse":
        return cls(
            week_start=view.week_start,
            week_end=view.week_end,
            tournaments=[PlanningTournamentResponse.from_view(item) for item in view.tournaments],
        )


class PlanningTypeChangeCommand(BaseModel):
    tournament_type_id: int


class PlanningTypeChangeResponse(BaseModel):
    tournament: PlanningTournamentResponse
    new_type: PlanningTournamentTypeResponse

    @classmethod
    def from_view(
        cls,
        view: TournamentCalendarTypeChangePreviewView,
    ) -> "PlanningTypeChangeResponse":
        return cls(
            tournament=PlanningTournamentResponse.from_view(view.tournament),
            new_type=PlanningTournamentTypeResponse.from_view(view.new_type),
        )


class PlanningDeletePreviewResponse(BaseModel):
    tournament: PlanningTournamentResponse
    registrations_count: int

    @classmethod
    def from_view(
        cls,
        view: TournamentCalendarDeletePreviewView,
    ) -> "PlanningDeletePreviewResponse":
        return cls(
            tournament=PlanningTournamentResponse.from_view(view.tournament),
            registrations_count=view.registrations_count,
        )


class PlanningDeleteResponse(BaseModel):
    tournament: PlanningTournamentResponse
