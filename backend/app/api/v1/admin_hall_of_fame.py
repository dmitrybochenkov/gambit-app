from typing import Annotated, Never

from fastapi import APIRouter, Depends, Query

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.admin_hall_of_fame import (
    HallOfFameAchievementCommand,
    HallOfFameAchievementTypeListResponse,
    HallOfFameAchievementTypeResponse,
    HallOfFameManagementEntryResponse,
    HallOfFameManagementPlayerListResponse,
    HallOfFameManagementSeasonListResponse,
    HallOfFameManagementSeasonResponse,
)
from app.services.access_policy import ActiveUserRequiredError, AdminAccessDeniedError
from app.services.hall_of_fame_management_service import (
    HallOfFameAchievementNotFoundError,
    HallOfFameAchievementTypeNotFoundError,
    HallOfFameSeasonNotFoundError,
    HallOfFameSingletonConflictError,
    hall_of_fame_management_service,
)
from app.services.user_common import UserNotFoundError

router = APIRouter(prefix="/admin/hall-of-fame", tags=["webapp-admin"])


def _raise_hall_error(exc: Exception) -> Never:
    if isinstance(
        exc,
        (
            HallOfFameAchievementNotFoundError,
            HallOfFameAchievementTypeNotFoundError,
            HallOfFameSeasonNotFoundError,
            UserNotFoundError,
        ),
    ):
        raise errors.not_found("Hall of Fame resource not found") from exc
    if isinstance(exc, HallOfFameSingletonConflictError):
        raise errors.conflict("Hall of Fame singleton state conflict") from exc
    raise exc


@router.get("/seasons", response_model=HallOfFameManagementSeasonListResponse)
async def list_hall_seasons(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> HallOfFameManagementSeasonListResponse:
    try:
        seasons = await hall_of_fame_management_service.list_seasons(actor.telegram_id)
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    return HallOfFameManagementSeasonListResponse(
        items=[HallOfFameManagementSeasonResponse.from_view(item) for item in seasons]
    )


@router.get(
    "/seasons/{season_id}",
    response_model=HallOfFameManagementEntryResponse,
)
async def get_hall_season(
    season_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> HallOfFameManagementEntryResponse:
    try:
        entry = await hall_of_fame_management_service.get_season_hall_of_fame(
            actor.telegram_id,
            season_id,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except HallOfFameSeasonNotFoundError as exc:
        _raise_hall_error(exc)
    return HallOfFameManagementEntryResponse.from_view(entry)


@router.get(
    "/achievement-types",
    response_model=HallOfFameAchievementTypeListResponse,
)
async def list_hall_achievement_types(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> HallOfFameAchievementTypeListResponse:
    try:
        achievement_types = await hall_of_fame_management_service.list_achievement_types(
            actor.telegram_id
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    return HallOfFameAchievementTypeListResponse(
        items=[HallOfFameAchievementTypeResponse.from_view(item) for item in achievement_types]
    )


@router.get("/players", response_model=HallOfFameManagementPlayerListResponse)
async def search_hall_players(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    query: Annotated[str, Query(min_length=1)],
) -> HallOfFameManagementPlayerListResponse:
    try:
        players = await hall_of_fame_management_service.search_players(actor.telegram_id, query)
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    return HallOfFameManagementPlayerListResponse.from_views(players)


@router.post("/achievements", response_model=HallOfFameManagementEntryResponse)
async def set_hall_achievement(
    request: HallOfFameAchievementCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> HallOfFameManagementEntryResponse:
    try:
        entry = await hall_of_fame_management_service.set_achievement(
            actor.telegram_id,
            request.season_id,
            request.player_id,
            request.kind,
            request.awarded_at,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        HallOfFameAchievementTypeNotFoundError,
        HallOfFameSeasonNotFoundError,
        HallOfFameSingletonConflictError,
        UserNotFoundError,
    ) as exc:
        _raise_hall_error(exc)
    return HallOfFameManagementEntryResponse.from_view(entry)


@router.delete(
    "/achievements/{achievement_id}",
    response_model=HallOfFameManagementEntryResponse,
)
async def delete_hall_achievement(
    achievement_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> HallOfFameManagementEntryResponse:
    try:
        entry = await hall_of_fame_management_service.delete_achievement(
            actor.telegram_id,
            achievement_id,
        )
    except (ActiveUserRequiredError, AdminAccessDeniedError) as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (HallOfFameAchievementNotFoundError, HallOfFameSeasonNotFoundError) as exc:
        _raise_hall_error(exc)
    return HallOfFameManagementEntryResponse.from_view(entry)
