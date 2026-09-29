from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api import errors
from app.api.business_notification_dependencies import check_in_notification_delivery
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.admin_check_in import (
    AdminCheckedInPlayersResponse,
    AdminCheckInDecisionResponse,
    AdminCheckInRequest,
    AdminCheckInResponse,
    AdminCheckInResultResponse,
    AdminExistingParticipantRequest,
    AdminExistingPlayerCheckInRequest,
    AdminNewParticipantRequest,
    AdminParticipantCreateRequest,
    AdminParticipantDeleteResponse,
    AdminPlayerListResponse,
    AdminPlayerResponse,
    participant_results_response,
)
from app.api.v1.schemas.admin_tournaments import AdminTournamentResultsResponse
from app.services.access_policy import AdminAccessDeniedError
from app.services.business_notification_use_cases import (
    CheckInNotificationDelivery,
    CheckInUseCases,
)
from app.services.player_reward_service import (
    PlayerRewardAlreadyRedeemedTodayError,
    PlayerRewardNotFoundError,
)
from app.services.result_errors import (
    FutureTournamentCannotBeClosedError,
    ResultDuplicateNameError,
    ResultPlayerAlreadyAddedError,
    ResultPlayerRewardConflictError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    TournamentResultsEditingUnavailableError,
)
from app.services.tournament_check_in_service import (
    TournamentCheckInClosedError,
    TournamentCheckInDuplicateNameError,
    TournamentCheckInGenderAlreadySetError,
    TournamentCheckInGenderDecisionRequiredError,
    TournamentCheckInNotFoundError,
    TournamentCheckInUserNotFoundError,
    tournament_check_in_service,
)
from app.services.tournament_participant_service import tournament_participant_service
from app.services.user_common import IdentityAlreadyExistsError

router = APIRouter(prefix="/admin/tournaments", tags=["webapp-admin"])


@router.get("/{tournament_id}/check-in", response_model=AdminCheckInResponse)
async def get_check_in(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminCheckInResponse:
    try:
        view = await tournament_check_in_service.get_check_in(actor.user_id, tournament_id)
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except TournamentCheckInNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except TournamentCheckInClosedError as exc:
        raise errors.conflict("Tournament check-in is unavailable") from exc
    return AdminCheckInResponse.from_view(view)


@router.get("/{tournament_id}/check-in/players", response_model=AdminCheckedInPlayersResponse)
async def get_checked_in_players(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminCheckedInPlayersResponse:
    try:
        view = await tournament_check_in_service.get_checked_in_players(
            actor.user_id,
            tournament_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except TournamentCheckInNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except TournamentCheckInClosedError as exc:
        raise errors.conflict("Tournament check-in is unavailable") from exc
    return AdminCheckedInPlayersResponse.from_view(view)


@router.get("/{tournament_id}/check-in/registered", response_model=AdminPlayerListResponse)
async def search_registered_players(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    query: Annotated[str, Query(min_length=1)],
) -> AdminPlayerListResponse:
    try:
        candidates = await tournament_check_in_service.search_registered(
            actor.user_id,
            tournament_id,
            query,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except TournamentCheckInNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except TournamentCheckInClosedError as exc:
        raise errors.conflict("Tournament check-in is unavailable") from exc
    return AdminPlayerListResponse(
        items=[
            AdminPlayerResponse(id=item.user_id, display_name=item.display_name, gender=None)
            for item in candidates
        ]
    )


@router.get("/{tournament_id}/check-in/users", response_model=AdminPlayerListResponse)
async def search_existing_players(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    query: Annotated[str, Query(min_length=1)],
) -> AdminPlayerListResponse:
    try:
        users = await tournament_check_in_service.search_users(
            actor.user_id,
            tournament_id,
            query,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except TournamentCheckInNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except TournamentCheckInClosedError as exc:
        raise errors.conflict("Tournament check-in is unavailable") from exc
    return AdminPlayerListResponse(items=[AdminPlayerResponse.from_view(item) for item in users])


@router.get(
    "/{tournament_id}/check-in/players/{player_id}/decision",
    response_model=AdminCheckInDecisionResponse,
)
async def get_check_in_decision(
    tournament_id: int,
    player_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminCheckInDecisionResponse:
    try:
        view = await tournament_check_in_service.get_user_check_in_decision(
            actor.user_id,
            tournament_id,
            player_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except (TournamentCheckInNotFoundError, TournamentCheckInUserNotFoundError) as exc:
        raise errors.not_found("Tournament or player not found") from exc
    except TournamentCheckInClosedError as exc:
        raise errors.conflict("Tournament check-in is unavailable") from exc
    return AdminCheckInDecisionResponse.from_view(view)


@router.post(
    "/{tournament_id}/check-ins",
    response_model=AdminCheckInResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def complete_check_in(
    tournament_id: int,
    request: AdminCheckInRequest,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    delivery: Annotated[CheckInNotificationDelivery, Depends(check_in_notification_delivery)],
) -> AdminCheckInResultResponse:
    use_cases = CheckInUseCases(tournament_check_in_service)
    try:
        if isinstance(request, AdminExistingPlayerCheckInRequest):
            view = await use_cases.complete_user_check_in(
                actor_user_id=actor.user_id,
                tournament_id=tournament_id,
                user_id=request.player_id,
                delivery=delivery,
                gender_decision=request.gender_decision,
                reward_id=request.reward_id,
            )
        else:
            view = await use_cases.create_user_and_check_in(
                actor_user_id=actor.user_id,
                tournament_id=tournament_id,
                display_name=request.display_name,
                gender=request.gender,
                delivery=delivery,
            )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except (TournamentCheckInNotFoundError, TournamentCheckInUserNotFoundError) as exc:
        raise errors.not_found("Tournament or player not found") from exc
    except TournamentCheckInClosedError as exc:
        raise errors.conflict("Tournament check-in is unavailable") from exc
    except TournamentCheckInGenderDecisionRequiredError as exc:
        raise errors.validation_error("Gender decision is required") from exc
    except TournamentCheckInGenderAlreadySetError as exc:
        raise errors.conflict("Player gender is already set") from exc
    except (TournamentCheckInDuplicateNameError, IdentityAlreadyExistsError) as exc:
        raise errors.conflict("Player already exists") from exc
    except PlayerRewardNotFoundError as exc:
        raise errors.not_found("Reward not found") from exc
    except PlayerRewardAlreadyRedeemedTodayError as exc:
        raise errors.conflict("A reward was already redeemed today") from exc
    return AdminCheckInResultResponse.from_view(view)


@router.get("/{tournament_id}/participants/candidates", response_model=AdminPlayerListResponse)
async def search_participant_candidates(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    query: Annotated[str, Query(min_length=1)],
) -> AdminPlayerListResponse:
    try:
        users = await tournament_participant_service.search_existing_users_for_tournament(
            actor.user_id,
            tournament_id,
            query,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except ResultTournamentNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament participants are not editable") from exc
    return AdminPlayerListResponse(items=[AdminPlayerResponse.from_view(item) for item in users])


@router.post(
    "/{tournament_id}/participants",
    response_model=AdminTournamentResultsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_participant(
    tournament_id: int,
    request: AdminParticipantCreateRequest,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminTournamentResultsResponse:
    try:
        if isinstance(request, AdminExistingParticipantRequest):
            view = await tournament_participant_service.add_existing_player_to_tournament(
                actor.user_id,
                tournament_id,
                request.player_id,
            )
        elif isinstance(request, AdminNewParticipantRequest):
            view = await tournament_participant_service.add_new_player_to_tournament(
                actor.user_id,
                tournament_id,
                request.display_name,
            )
        else:
            raise AssertionError("Unsupported participant request")
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Admin access required") from exc
    except (ResultTournamentNotFoundError, ResultUserNotFoundError) as exc:
        raise errors.not_found("Tournament or player not found") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament participants are not editable") from exc
    except (ResultDuplicateNameError, IdentityAlreadyExistsError) as exc:
        raise errors.conflict("Player already exists") from exc
    except ResultPlayerAlreadyAddedError as exc:
        raise errors.conflict("Player is already in tournament") from exc
    return participant_results_response(view)


@router.delete(
    "/{tournament_id}/participants/{player_id}",
    response_model=AdminParticipantDeleteResponse,
)
async def delete_participant(
    tournament_id: int,
    player_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminParticipantDeleteResponse:
    try:
        view = await tournament_participant_service.delete_player_from_open_tournament(
            actor.user_id,
            tournament_id,
            player_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (ResultTournamentNotFoundError, ResultUserNotFoundError) as exc:
        raise errors.not_found("Tournament or player not found") from exc
    except FutureTournamentCannotBeClosedError as exc:
        raise errors.conflict("Tournament participant cannot be removed") from exc
    except ResultPlayerRewardConflictError as exc:
        raise errors.conflict("Player has tournament reward data") from exc
    return AdminParticipantDeleteResponse.from_view(view)
