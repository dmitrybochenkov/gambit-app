from typing import Annotated

from fastapi import APIRouter, Depends

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.hall_of_fame import HallOfFameResponse
from app.services.user_statistics_service import (
    HallOfFameNotAllowedError,
    user_statistics_service,
)

router = APIRouter(tags=["webapp"])


@router.get("/hall-of-fame", response_model=HallOfFameResponse)
async def get_hall_of_fame(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> HallOfFameResponse:
    try:
        seasons = await user_statistics_service.get_hall_of_fame(actor.telegram_id)
    except HallOfFameNotAllowedError as exc:
        raise errors.forbidden("Hall of Fame is unavailable") from exc
    return HallOfFameResponse.from_views(seasons)
