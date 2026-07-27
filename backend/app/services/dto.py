from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class UserStatusView(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class UserRoleView(StrEnum):
    PLAYER = "player"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class SeasonStatusView(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


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
    status: SeasonStatusView
    scoring_config_id: int


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
class TournamentResultDraftPlayerView:
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int


@dataclass(frozen=True)
class TournamentResultDraftView:
    tournament: TournamentView
    points_pool: Decimal | None
    players: list[TournamentResultDraftPlayerView]
    knockout_mode: str = "none"


@dataclass(frozen=True)
class AdminPromptView:
    id: int
    kind: str
    payload: str
    status: str


@dataclass(frozen=True)
class TournamentTypeOptionView:
    id: int
    name: str


@dataclass(frozen=True)
class PointsRatingView:
    player_id: int
    display_name: str
    total_points: Decimal
    tournaments_count: int


@dataclass(frozen=True)
class KnockoutsRatingView:
    player_id: int
    display_name: str
    knockouts_count: int
    big_knockouts_count: int
    knockout_points: Decimal
    tournaments_count: int

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.big_knockouts_count


@dataclass(frozen=True)
class RatingResultView:
    title: str
    rows: list[PointsRatingView] | list[KnockoutsRatingView]
    current_player_id: int


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
