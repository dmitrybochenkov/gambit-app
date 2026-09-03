from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.profile import PlayerProfileResponse
from app.services.profile_service import (
    ProfileFutureSeasonError,
    ProfileKind,
    ProfileNotAllowedError,
    ProfileSeasonNotFoundError,
    profile_service,
)

router = APIRouter(tags=["webapp"])


@router.get("/me/profile", response_model=PlayerProfileResponse)
async def get_my_profile(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    season_id: Annotated[int | None, Query()] = None,
) -> PlayerProfileResponse:
    try:
        title, profile = await profile_service.get_profile_for_player(
            actor.telegram_id,
            kind=(
                ProfileKind.SELECTED_SEASON if season_id is not None else ProfileKind.CURRENT_SEASON
            ),
            season_id=season_id,
        )
    except ProfileNotAllowedError as exc:
        raise errors.forbidden("Profile is unavailable") from exc
    except ProfileSeasonNotFoundError as exc:
        raise errors.not_found("Season not found") from exc
    except ProfileFutureSeasonError as exc:
        raise errors.validation_error("Season is not available yet") from exc
    if profile is None:
        raise errors.not_found("Profile not found")
    return PlayerProfileResponse.from_view(
        user_id=actor.user_id,
        gender=actor.gender,
        title=title,
        view=profile,
    )
