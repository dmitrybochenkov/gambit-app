from typing import Annotated, Never

from fastapi import APIRouter, Depends, Query

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.registration_review_dependencies import registration_review_notification_delivery
from app.api.v1.schemas.admin_registrations import (
    AdminRegistrationApproveCommand,
    AdminRegistrationCandidateCommand,
    AdminRegistrationReviewOutcomeResponse,
    AdminRegistrationReviewPageResponse,
    AdminRegistrationReviewResponse,
)
from app.services.access_policy import AdminAccessDeniedError
from app.services.registration_review_service import registration_review_service
from app.services.registration_review_use_cases import (
    RegistrationReviewNotificationDelivery,
    registration_review_use_cases,
)
from app.services.user_common import (
    IdentityAlreadyExistsError,
    RegistrationAlreadyReviewedError,
    RegistrationCandidateNotFoundError,
    RegistrationNotAllowedError,
    RegistrationRequestNotFoundError,
)

router = APIRouter(prefix="/admin/registrations", tags=["webapp-admin"])


def _raise_registration_review_error(exc: Exception) -> Never:
    if isinstance(exc, RegistrationRequestNotFoundError):
        raise errors.not_found("Registration request not found") from exc
    if isinstance(exc, RegistrationCandidateNotFoundError):
        raise errors.not_found("Registration candidate not found") from exc
    if isinstance(exc, RegistrationAlreadyReviewedError):
        raise errors.conflict("Registration request was already reviewed") from exc
    if isinstance(exc, (IdentityAlreadyExistsError, RegistrationNotAllowedError)):
        raise errors.conflict("Registration request cannot be approved") from exc
    raise exc


@router.get("/pending", response_model=AdminRegistrationReviewPageResponse)
async def list_pending_registration_reviews(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    page: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=100)] = 5,
) -> AdminRegistrationReviewPageResponse:
    try:
        result = await registration_review_service.list_pending_reviews_page_for_superadmin(
            actor.telegram_id,
            page=page,
            page_size=page_size,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    return AdminRegistrationReviewPageResponse.from_page(result)


@router.get("/{request_id}", response_model=AdminRegistrationReviewResponse)
async def get_registration_review(
    request_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminRegistrationReviewResponse:
    try:
        view = await registration_review_service.get_registration_review_for_admin(
            actor.telegram_id,
            request_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        RegistrationAlreadyReviewedError,
        RegistrationRequestNotFoundError,
    ) as exc:
        _raise_registration_review_error(exc)
    return AdminRegistrationReviewResponse.from_view(view)


@router.post("/{request_id}/candidate", response_model=AdminRegistrationReviewResponse)
async def validate_registration_candidate(
    request_id: int,
    request: AdminRegistrationCandidateCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminRegistrationReviewResponse:
    try:
        view = await registration_review_service.select_registration_candidate(
            actor.telegram_id,
            request_id,
            request.candidate_user_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        RegistrationAlreadyReviewedError,
        RegistrationCandidateNotFoundError,
        RegistrationRequestNotFoundError,
    ) as exc:
        _raise_registration_review_error(exc)
    return AdminRegistrationReviewResponse.from_view(view)


@router.post("/{request_id}/approve", response_model=AdminRegistrationReviewOutcomeResponse)
async def approve_registration(
    request_id: int,
    request: AdminRegistrationApproveCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    delivery: Annotated[
        RegistrationReviewNotificationDelivery,
        Depends(registration_review_notification_delivery),
    ],
) -> AdminRegistrationReviewOutcomeResponse:
    try:
        outcome = await registration_review_use_cases.approve(
            reviewer_telegram_id=actor.telegram_id,
            request_id=request_id,
            candidate_user_id=request.candidate_user_id,
            delivery=delivery,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        IdentityAlreadyExistsError,
        RegistrationAlreadyReviewedError,
        RegistrationCandidateNotFoundError,
        RegistrationNotAllowedError,
        RegistrationRequestNotFoundError,
    ) as exc:
        _raise_registration_review_error(exc)
    return AdminRegistrationReviewOutcomeResponse.from_view(outcome)


@router.post("/{request_id}/reject", response_model=AdminRegistrationReviewOutcomeResponse)
async def reject_registration(
    request_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    delivery: Annotated[
        RegistrationReviewNotificationDelivery,
        Depends(registration_review_notification_delivery),
    ],
) -> AdminRegistrationReviewOutcomeResponse:
    try:
        outcome = await registration_review_use_cases.reject(
            reviewer_telegram_id=actor.telegram_id,
            request_id=request_id,
            delivery=delivery,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        RegistrationAlreadyReviewedError,
        RegistrationRequestNotFoundError,
    ) as exc:
        _raise_registration_review_error(exc)
    return AdminRegistrationReviewOutcomeResponse.from_view(outcome)
