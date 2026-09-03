from typing import Annotated

from fastapi import APIRouter, Depends

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.history import PlayerHistoryDetailResponse, PlayerHistoryListResponse
from app.services.user_statistics_service import (
    HistoricalTournamentNotFoundError,
    HistoryNotAllowedError,
    user_statistics_service,
)

router = APIRouter(tags=["webapp"])


@router.get("/me/history", response_model=PlayerHistoryListResponse)
async def get_my_history(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlayerHistoryListResponse:
    try:
        history = await user_statistics_service.list_player_history(actor.telegram_id)
    except HistoryNotAllowedError as exc:
        raise errors.forbidden("History is unavailable") from exc
    return PlayerHistoryListResponse.from_views(history)


@router.get("/me/history/{tournament_id}", response_model=PlayerHistoryDetailResponse)
async def get_my_history_detail(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlayerHistoryDetailResponse:
    try:
        result = await user_statistics_service.get_player_history_tournament_result(
            actor.telegram_id,
            tournament_id,
        )
    except HistoryNotAllowedError as exc:
        raise errors.forbidden("History is unavailable") from exc
    except HistoricalTournamentNotFoundError as exc:
        raise errors.not_found("Tournament result not found") from exc
    return PlayerHistoryDetailResponse.from_view(player_id=actor.user_id, view=result)
