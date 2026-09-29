from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.media_dependencies import media_read_service
from app.services.access_policy import ActiveUserRequiredError
from app.services.media_read_service import (
    MediaNotFoundError,
    MediaReadService,
    MediaUnavailableError,
)

router = APIRouter(prefix="/media", tags=["webapp-media"])


@router.get("/tournament-photos/{photo_id}/content", response_class=Response)
async def get_tournament_photo_content(
    photo_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    service: Annotated[MediaReadService, Depends(media_read_service)],
) -> Response:
    try:
        content = await service.get_tournament_photo(actor.user_id, photo_id)
    except ActiveUserRequiredError as exc:
        raise errors.forbidden("Photo is unavailable") from exc
    except MediaNotFoundError as exc:
        raise errors.not_found("Photo not found") from exc
    except MediaUnavailableError as exc:
        raise errors.api_error(
            status.HTTP_502_BAD_GATEWAY,
            "media_unavailable",
            "Photo is temporarily unavailable",
        ) from exc
    return _image_response(content.data, content.content_type)


@router.get("/hall-of-fame-photos/{photo_id}/content", response_class=Response)
async def get_hall_of_fame_photo_content(
    photo_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    service: Annotated[MediaReadService, Depends(media_read_service)],
) -> Response:
    try:
        content = await service.get_hall_of_fame_photo(actor.user_id, photo_id)
    except ActiveUserRequiredError as exc:
        raise errors.forbidden("Hall of Fame is unavailable") from exc
    except MediaNotFoundError as exc:
        raise errors.not_found("Photo not found") from exc
    except MediaUnavailableError as exc:
        raise errors.api_error(
            status.HTTP_502_BAD_GATEWAY,
            "media_unavailable",
            "Photo is temporarily unavailable",
        ) from exc
    return _image_response(content.data, content.content_type)


def _image_response(data: bytes, content_type: str) -> Response:
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": "inline"},
    )
