from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.admin_tournaments import (
    AdminCombinationCreateRequest,
    AdminResultFieldUpdateRequest,
    AdminTournamentCombinationsResponse,
    AdminTournamentListResponse,
    AdminTournamentResponse,
    AdminTournamentResultsResponse,
)
from app.services.access_policy import AdminAccessDeniedError
from app.services.result_errors import (
    ResultCombinationNotFoundError,
    ResultInvalidCombinationRankError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    TournamentResultsEditingUnavailableError,
)
from app.services.result_service import result_service
from app.services.tournament_combination_service import tournament_combination_service

router = APIRouter(prefix="/admin/tournaments", tags=["webapp-admin"])


@router.get("", response_model=AdminTournamentListResponse)
async def list_editable_tournaments(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminTournamentListResponse:
    try:
        tournaments = await result_service.list_editable_tournaments(actor.telegram_id)
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    return AdminTournamentListResponse(
        items=[AdminTournamentResponse.from_view(item) for item in tournaments]
    )


@router.get("/{tournament_id}/results", response_model=AdminTournamentResultsResponse)
async def get_tournament_results(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminTournamentResultsResponse:
    try:
        view = await result_service.get_tournament_results(actor.telegram_id, tournament_id)
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except ResultTournamentNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament results are not editable") from exc
    return AdminTournamentResultsResponse.from_view(view)


@router.patch(
    "/{tournament_id}/results/{player_id}",
    response_model=AdminTournamentResultsResponse,
)
async def update_tournament_result(
    tournament_id: int,
    player_id: int,
    request: AdminResultFieldUpdateRequest,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminTournamentResultsResponse:
    try:
        view = await result_service.update_player_result_field(
            actor.telegram_id,
            tournament_id,
            player_id,
            request.field,
            request.value,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except (ResultTournamentNotFoundError, ResultUserNotFoundError) as exc:
        raise errors.not_found("Tournament result not found") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament results are not editable") from exc
    except ValueError as exc:
        raise errors.validation_error("Invalid tournament result value") from exc
    return AdminTournamentResultsResponse.from_view(view)


@router.get(
    "/{tournament_id}/combinations",
    response_model=AdminTournamentCombinationsResponse,
)
async def list_tournament_combinations(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminTournamentCombinationsResponse:
    try:
        view = await tournament_combination_service.list_for_tournament(
            actor.telegram_id,
            tournament_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except ResultTournamentNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament combinations are not editable") from exc
    return AdminTournamentCombinationsResponse.from_view(view)


@router.post(
    "/{tournament_id}/combinations",
    response_model=AdminTournamentCombinationsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_tournament_combination(
    tournament_id: int,
    request: AdminCombinationCreateRequest,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminTournamentCombinationsResponse:
    try:
        view = await tournament_combination_service.add_combination(
            actor.telegram_id,
            tournament_id,
            request.player_id,
            request.combination_type,
            request.rank,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except (ResultTournamentNotFoundError, ResultUserNotFoundError) as exc:
        raise errors.not_found("Tournament result not found") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament combinations are not editable") from exc
    except ResultInvalidCombinationRankError as exc:
        raise errors.validation_error("Invalid combination rank") from exc
    return AdminTournamentCombinationsResponse.from_view(view)


@router.delete(
    "/{tournament_id}/combinations/{combination_id}",
    response_model=AdminTournamentCombinationsResponse,
)
async def delete_tournament_combination(
    tournament_id: int,
    combination_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminTournamentCombinationsResponse:
    try:
        view = await tournament_combination_service.delete_combination(
            actor.telegram_id,
            tournament_id,
            combination_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except ResultTournamentNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except ResultCombinationNotFoundError as exc:
        raise errors.not_found("Combination not found") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament combinations are not editable") from exc
    return AdminTournamentCombinationsResponse.from_view(view)
