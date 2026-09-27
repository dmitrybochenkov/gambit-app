from typing import Annotated, Never

from fastapi import APIRouter, Depends, Query

from app.api import errors
from app.api.admin_management_dependencies import admin_promotion_notification_delivery
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.admin_users import (
    AdminUserGenderCommand,
    AdminUserListResponse,
    AdminUserRenameCommand,
    AdminUserResponse,
)
from app.services.access_policy import ActiveUserRequiredError, AdminAccessDeniedError
from app.services.admin_management_service import (
    AdminPromotionNotEligibleError,
    admin_management_service,
)
from app.services.admin_management_use_cases import (
    AdminPromotionNotificationDelivery,
    admin_management_use_cases,
)
from app.services.player_search import InvalidDisplayNameError
from app.services.user_common import UserNotFoundError, UserRoleAlreadyAssignedError
from app.services.user_rename_service import (
    UserRenameNameOccupiedError,
    UserRenameSameNameError,
    UserRenameStaleError,
    user_rename_service,
)

router = APIRouter(prefix="/admin/users", tags=["webapp-admin"])


def _raise_user_management_error(exc: Exception) -> Never:
    if isinstance(exc, UserNotFoundError):
        raise errors.not_found("User not found") from exc
    if isinstance(exc, InvalidDisplayNameError):
        raise errors.validation_error("Invalid display name") from exc
    if isinstance(
        exc,
        (
            AdminPromotionNotEligibleError,
            UserRenameNameOccupiedError,
            UserRenameSameNameError,
            UserRenameStaleError,
            UserRoleAlreadyAssignedError,
        ),
    ):
        raise errors.conflict("User state conflict") from exc
    raise exc


@router.get("", response_model=AdminUserListResponse)
async def search_users(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    query: Annotated[str, Query(min_length=1)],
) -> AdminUserListResponse:
    try:
        users = await user_rename_service.search_users_for_rename(actor.telegram_id, query)
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    return AdminUserListResponse(items=[AdminUserResponse.from_view(user) for user in users])


@router.get("/admin-candidates", response_model=AdminUserListResponse)
async def search_admin_candidates(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    query: Annotated[str, Query(min_length=1)],
) -> AdminUserListResponse:
    try:
        users = await admin_management_service.search_admin_candidates_for_superadmin(
            actor.telegram_id,
            query,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    return AdminUserListResponse(items=[AdminUserResponse.from_view(user) for user in users])


@router.get("/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminUserResponse:
    try:
        user = await user_rename_service.get_target_for_rename(actor.telegram_id, user_id)
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except UserNotFoundError as exc:
        _raise_user_management_error(exc)
    return AdminUserResponse.from_view(user)


@router.post("/{user_id}/promote-admin", response_model=AdminUserResponse)
async def promote_admin(
    user_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    delivery: Annotated[
        AdminPromotionNotificationDelivery,
        Depends(admin_promotion_notification_delivery),
    ],
) -> AdminUserResponse:
    try:
        user = await admin_management_use_cases.promote_admin(
            superadmin_telegram_id=actor.telegram_id,
            user_id=user_id,
            delivery=delivery,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        AdminPromotionNotEligibleError,
        UserNotFoundError,
        UserRoleAlreadyAssignedError,
    ) as exc:
        _raise_user_management_error(exc)
    return AdminUserResponse.from_view(user)


@router.patch("/{user_id}/name", response_model=AdminUserResponse)
async def rename_user(
    user_id: int,
    request: AdminUserRenameCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminUserResponse:
    try:
        user = await user_rename_service.rename_user(
            actor.telegram_id,
            user_id,
            request.display_name,
            request.expected_old_display_name,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        InvalidDisplayNameError,
        UserNotFoundError,
        UserRenameNameOccupiedError,
        UserRenameSameNameError,
        UserRenameStaleError,
    ) as exc:
        _raise_user_management_error(exc)
    return AdminUserResponse.from_view(user)


@router.patch("/{user_id}/gender", response_model=AdminUserResponse)
async def set_user_gender(
    user_id: int,
    request: AdminUserGenderCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminUserResponse:
    try:
        user = await user_rename_service.set_user_gender_by_superadmin(
            actor.telegram_id,
            user_id,
            request.gender,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except UserNotFoundError as exc:
        _raise_user_management_error(exc)
    return AdminUserResponse.from_view(user)
