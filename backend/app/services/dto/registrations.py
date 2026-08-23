from dataclasses import dataclass
from datetime import date

from app.services.dto.users import UserView


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
    selected_candidate: RegistrationCandidateView | None = None


@dataclass(frozen=True)
class AdminPanelView:
    admin: UserView
    reviews: list[RegistrationReviewView]
    active_telegram_users_count: int = 0


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
class TournamentRegistrationCountView:
    tournament_id: int
    date: date
    tournament_type_name: str
    registrations_count: int


@dataclass(frozen=True)
class TournamentRegistrationPlayerView:
    user_id: int
    display_name: str


@dataclass(frozen=True)
class TournamentRegistrationsDetailView:
    tournament_id: int
    date: date
    tournament_type_name: str
    players: list[TournamentRegistrationPlayerView]


@dataclass(frozen=True)
class RegistrationsOverviewView:
    pending_user_registration_count: int
    active_tournament_registration_count: int
    tournaments: list[TournamentRegistrationCountView]

    @property
    def has_user_registrations(self) -> bool:
        return self.pending_user_registration_count > 0

    @property
    def has_tournament_registrations(self) -> bool:
        return self.active_tournament_registration_count > 0
