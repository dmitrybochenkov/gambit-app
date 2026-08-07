from dataclasses import dataclass

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
