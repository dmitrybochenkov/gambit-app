from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.db.models.enums import AdminPromptKind, AdminPromptStatus


class UserStatusView(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class UserRoleView(StrEnum):
    PLAYER = "player"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class SeasonLifecycleStateView(StrEnum):
    SCHEDULED = "scheduled"
    CURRENT = "current"
    COMPLETED = "completed"


class UserStartStatusView(StrEnum):
    REGISTERED = "registered"
    PENDING_REGISTRATION = "pending_registration"
    BLOCKED = "blocked"
    NEEDS_REGISTRATION = "needs_registration"


@dataclass(frozen=True)
class UserView:
    id: int
    telegram_id: int | None
    display_name: str
    status: UserStatusView
    role: UserRoleView

    @property
    def is_active(self) -> bool:
        return self.status == UserStatusView.ACTIVE

    @property
    def is_blocked(self) -> bool:
        return self.status == UserStatusView.BLOCKED

    @property
    def is_admin(self) -> bool:
        return self.role in {UserRoleView.ADMIN, UserRoleView.SUPERADMIN}


@dataclass(frozen=True)
class UserStartView:
    status: UserStartStatusView
    user: UserView | None = None

    def __post_init__(self) -> None:
        user_required = self.status in {
            UserStartStatusView.REGISTERED,
            UserStartStatusView.BLOCKED,
        }
        if user_required and self.user is None:
            raise ValueError(f"{self.status.value} start view requires user")
        if not user_required and self.user is not None:
            raise ValueError(f"{self.status.value} start view cannot include user")

    @classmethod
    def registered(cls, user: UserView) -> "UserStartView":
        return cls(status=UserStartStatusView.REGISTERED, user=user)

    @classmethod
    def blocked(cls, user: UserView) -> "UserStartView":
        return cls(status=UserStartStatusView.BLOCKED, user=user)

    @classmethod
    def pending_registration(cls) -> "UserStartView":
        return cls(status=UserStartStatusView.PENDING_REGISTRATION)

    @classmethod
    def needs_registration(cls) -> "UserStartView":
        return cls(status=UserStartStatusView.NEEDS_REGISTRATION)

    @property
    def required_user(self) -> UserView:
        if self.user is None:
            raise ValueError(f"{self.status.value} start view has no user")
        return self.user


@dataclass(frozen=True)
class RegistrationCandidateView:
    user: UserView
    score: int
    reason: str


@dataclass(frozen=True)
class RegistrationRequestView:
    id: int
    telegram_id: int
    request_type: str
    status: str
    requested_display_name: str | None
    requested_link_name: str | None
    candidate_user_id: int | None
    created_at: str


@dataclass(frozen=True)
class RegistrationReviewView:
    request: RegistrationRequestView
    candidates: list[RegistrationCandidateView]


@dataclass(frozen=True)
class AdminPanelView:
    admin: UserView
    reviews: list[RegistrationReviewView]


@dataclass(frozen=True)
class RegistrationNotificationView:
    request: RegistrationRequestView
    admins: list[UserView]
    candidates: list[RegistrationCandidateView]


@dataclass(frozen=True)
class RegistrationReviewResultView:
    user: UserView | None
    request: RegistrationRequestView
    admins: list[UserView]


@dataclass(frozen=True)
class TournamentView:
    id: int
    date: date
    tournament_type_id: int
    tournament_type_name: str | None


@dataclass(frozen=True)
class SeasonView:
    id: int
    name: str
    starts_at: date
    ends_at: date | None
    lifecycle_state: SeasonLifecycleStateView
    scoring_config_id: int


@dataclass(frozen=True)
class SeasonProposalView:
    id: int
    name: str
    starts_at: date
    scoring_config_id: int
    active_season_ends_at: date | None = None


@dataclass(frozen=True)
class ScoringConfigView:
    id: int
    place_1_coefficient: Decimal
    place_2_coefficient: Decimal
    place_3_coefficient: Decimal
    place_4_coefficient: Decimal
    place_5_coefficient: Decimal
    knockout_small_points: int
    knockout_big_points: int


@dataclass(frozen=True)
class TournamentResultPlayerView:
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int = 0
    tournament_points: Decimal = Decimal("0")
    knockout_points: Decimal = Decimal("0")

    @property
    def total_points(self) -> Decimal:
        return self.tournament_points + self.knockout_points + Decimal(self.bonus_points)


@dataclass(frozen=True)
class TournamentResultsView:
    tournament: TournamentView
    tournament_fund: int | None
    players: list[TournamentResultPlayerView]
    knockout_mode: str = "none"
    supports_bonus_points: bool = False


@dataclass(frozen=True)
class CheckInCandidateView:
    user_id: int
    display_name: str
    is_pre_registered: bool
    is_checked_in: bool
    source: str | None = None
    has_result_data: bool = False


@dataclass(frozen=True)
class TournamentCheckInView:
    tournament: TournamentView
    registered_count: int
    checked_in_count: int
    unchecked_registered_count: int
    walk_in_count: int


@dataclass(frozen=True)
class AdminPromptView:
    id: int
    kind: AdminPromptKind
    payload: str
    status: AdminPromptStatus


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
class TournamentPromptView:
    id: int
    kind: AdminPromptKind
    status: AdminPromptStatus
    tournaments: list[TournamentPromptItemView]


@dataclass(frozen=True)
class TournamentPromptDayEditView:
    prompt_id: int
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


@dataclass(frozen=True)
class PointsRatingView:
    player_id: int
    display_name: str
    total_points: Decimal
    tournaments_count: int
    season_champion_titles_count: int = 0


@dataclass(frozen=True)
class KnockoutsRatingView:
    player_id: int
    display_name: str
    knockouts_count: int
    big_knockouts_count: int
    knockout_tournaments_count: int
    season_champion_titles_count: int = 0
    season_knockout_leader_titles_count: int = 0

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


@dataclass(frozen=True)
class RatingResultView:
    title: str
    rows: list[PointsRatingView] | list[KnockoutsRatingView]
    current_player_id: int


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


@dataclass(frozen=True)
class HallOfFameSeasonView:
    season_id: int
    season_name: str
    starts_at: date
    champion_player_id: int | None
    champion_display_name: str | None
    knockout_leader_player_id: int | None
    knockout_leader_display_name: str | None


@dataclass(frozen=True)
class PlayerProfileView:
    display_name: str
    total_points: Decimal
    knockout_points: Decimal
    knockouts_count: int
    big_knockouts_count: int
    tournaments_count: int
    first_places_count: int
    second_places_count: int
    third_places_count: int
    fourth_places_count: int
    fifth_places_count: int

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count
