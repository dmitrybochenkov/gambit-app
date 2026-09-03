from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.ratings import KnockoutsRatingResponse, PointsRatingResponse
from app.services.dto.statistics.rating import KnockoutsRatingView, PointsRatingView
from app.services.rating_service import (
    RatingFutureSeasonError,
    RatingKind,
    RatingNotAllowedError,
    RatingSeasonNotFoundError,
    rating_service,
)

router = APIRouter(tags=["webapp"])


@router.get("/ratings", response_model=PointsRatingResponse)
async def get_rating(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    season_id: Annotated[int | None, Query()] = None,
) -> PointsRatingResponse:
    try:
        result = await rating_service.get_rating_for_player(
            actor.telegram_id,
            kind=RatingKind.SELECTED_SEASON if season_id is not None else RatingKind.CURRENT_SEASON,
            season_id=season_id,
        )
    except RatingNotAllowedError as exc:
        raise errors.forbidden("Rating is unavailable") from exc
    except RatingSeasonNotFoundError as exc:
        raise errors.not_found("Season not found") from exc
    except RatingFutureSeasonError as exc:
        raise errors.validation_error("Season is not available yet") from exc
    return PointsRatingResponse.from_rows(
        result.title,
        [row for row in result.rows if isinstance(row, PointsRatingView)],
    )


@router.get("/ratings/knockouts", response_model=KnockoutsRatingResponse)
async def get_knockouts_rating(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    season_id: Annotated[int | None, Query()] = None,
) -> KnockoutsRatingResponse:
    try:
        result = await rating_service.get_rating_for_player(
            actor.telegram_id,
            kind=(
                RatingKind.KNOCKOUTS_SELECTED_SEASON
                if season_id is not None
                else RatingKind.KNOCKOUTS_CURRENT_SEASON
            ),
            season_id=season_id,
        )
    except RatingNotAllowedError as exc:
        raise errors.forbidden("Rating is unavailable") from exc
    except RatingSeasonNotFoundError as exc:
        raise errors.not_found("Season not found") from exc
    except RatingFutureSeasonError as exc:
        raise errors.validation_error("Season is not available yet") from exc
    return KnockoutsRatingResponse.from_rows(
        result.title,
        [row for row in result.rows if isinstance(row, KnockoutsRatingView)],
    )
