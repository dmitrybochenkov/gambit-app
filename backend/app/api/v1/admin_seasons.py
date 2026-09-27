from typing import Annotated, Never

from fastapi import APIRouter, Depends

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.admin_seasons import (
    SeasonCreateNextCommand,
    SeasonCreationPreviewResponse,
    SeasonFutureDeleteCommand,
    SeasonFutureDeletePreviewResponse,
    SeasonResponse,
    SeasonTimelineResponse,
)
from app.services.access_policy import AdminAccessDeniedError
from app.services.season_service import (
    SeasonConflictError,
    SeasonCurrentNotFoundError,
    SeasonDateOverlapError,
    SeasonFutureHasTournamentsError,
    SeasonFutureStaleError,
    SeasonNameAlreadyExistsError,
    SeasonNameInvalidError,
    SeasonNotFoundError,
    SeasonScheduledConflictError,
    SeasonScoringConfigAmbiguousError,
    SeasonScoringConfigNotFoundError,
    SeasonStartDateError,
    season_service,
)

router = APIRouter(prefix="/admin/seasons", tags=["webapp-admin"])

SEASON_EXPECTED_ERRORS = (
    SeasonConflictError,
    SeasonCurrentNotFoundError,
    SeasonDateOverlapError,
    SeasonFutureHasTournamentsError,
    SeasonFutureStaleError,
    SeasonNameAlreadyExistsError,
    SeasonNameInvalidError,
    SeasonNotFoundError,
    SeasonScheduledConflictError,
    SeasonScoringConfigAmbiguousError,
    SeasonScoringConfigNotFoundError,
    SeasonStartDateError,
)


def _raise_season_error(exc: Exception) -> Never:
    if isinstance(exc, SeasonNotFoundError):
        raise errors.not_found("Future season not found") from exc
    if isinstance(exc, (SeasonCurrentNotFoundError, SeasonScoringConfigNotFoundError)):
        raise errors.not_found("Required season configuration not found") from exc
    if isinstance(exc, (SeasonNameInvalidError, SeasonDateOverlapError, SeasonStartDateError)):
        raise errors.validation_error("Invalid season data") from exc
    if isinstance(exc, SeasonScoringConfigAmbiguousError):
        raise errors.conflict("Season scoring configuration is ambiguous") from exc
    if isinstance(exc, SeasonFutureStaleError):
        raise errors.conflict("Future season state is stale") from exc
    raise errors.conflict("Season timeline conflict") from exc


@router.get("", response_model=SeasonTimelineResponse)
async def get_season_timeline(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> SeasonTimelineResponse:
    try:
        view = await season_service.get_season_timeline(actor.telegram_id)
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except SEASON_EXPECTED_ERRORS as exc:
        _raise_season_error(exc)
    return SeasonTimelineResponse.from_view(view)


@router.post("/next/preview", response_model=SeasonCreationPreviewResponse)
async def preview_next_season(
    request: SeasonCreateNextCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> SeasonCreationPreviewResponse:
    try:
        view = await season_service.get_creation_preview(
            actor.telegram_id,
            name=request.name,
            starts_at=request.starts_at,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except SEASON_EXPECTED_ERRORS as exc:
        _raise_season_error(exc)
    return SeasonCreationPreviewResponse.from_view(view)


@router.post("/next", response_model=SeasonResponse)
async def create_next_season(
    request: SeasonCreateNextCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> SeasonResponse:
    try:
        view = await season_service.create_next_season(
            actor.telegram_id,
            name=request.name,
            starts_at=request.starts_at,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except SEASON_EXPECTED_ERRORS as exc:
        _raise_season_error(exc)
    return SeasonResponse.from_view(view)


@router.get("/future/delete-preview", response_model=SeasonFutureDeletePreviewResponse)
async def preview_future_season_deletion(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> SeasonFutureDeletePreviewResponse:
    try:
        view = await season_service.get_future_season_delete_preview(actor.telegram_id)
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except SEASON_EXPECTED_ERRORS as exc:
        _raise_season_error(exc)
    return SeasonFutureDeletePreviewResponse.from_view(view)


@router.delete("/future", response_model=SeasonTimelineResponse)
async def delete_future_season(
    request: SeasonFutureDeleteCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> SeasonTimelineResponse:
    try:
        view = await season_service.delete_future_season(
            actor.telegram_id,
            expected_season_id=request.expected_season_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except SEASON_EXPECTED_ERRORS as exc:
        _raise_season_error(exc)
    return SeasonTimelineResponse.from_view(view)
