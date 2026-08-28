from app.db.models import RegistrationRequest, User
from app.services.dto.registrations import RegistrationRequestView
from app.services.dto.users import UserView
from app.services.player_search import InvalidDisplayNameError as InvalidDisplayNameError
from app.services.player_search import PlayerSearchCandidate, validate_display_name


class IdentityAlreadyExistsError(ValueError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} already exists")


class DisplayNameLinkedUserExistsError(IdentityAlreadyExistsError):
    pass


class DisplayNameHistoricalUserExistsError(IdentityAlreadyExistsError):
    pass


class RegistrationNotAllowedError(ValueError):
    pass


class RegistrationRequestNotFoundError(ValueError):
    pass


class RegistrationAlreadyReviewedError(ValueError):
    pass


class UserNotFoundError(ValueError):
    pass


class RegistrationCandidateNotFoundError(ValueError):
    pass


class UserRoleAlreadyAssignedError(ValueError):
    pass


def user_view(user: User | None) -> UserView | None:
    if user is None:
        return None
    return required_user_view(user)


def required_user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        telegram_id=user.telegram_id,
        display_name=user.display_name,
        status=user.status,
        role=user.role,
        gender=user.gender,
    )


def registration_request_view(
    request: RegistrationRequest | None,
) -> RegistrationRequestView | None:
    if request is None:
        return None
    return required_registration_request_view(request)


def required_registration_request_view(
    request: RegistrationRequest,
) -> RegistrationRequestView:
    return RegistrationRequestView(
        id=request.id,
        telegram_id=request.telegram_id,
        request_type=request.request_type.value,
        status=request.status.value,
        requested_display_name=request.requested_display_name,
        requested_link_name=request.requested_link_name,
        candidate_user_id=request.candidate_user_id,
        created_at=request.created_at.strftime("%d.%m.%Y %H:%M"),
    )


def require_valid_display_name(display_name: str) -> str:
    return validate_display_name(display_name)


def registration_candidate_score(candidate: PlayerSearchCandidate) -> int:
    if candidate.score == 300:
        return 100
    if candidate.reason == "имя игрока частично совпадает":
        return 95
    return candidate.score
