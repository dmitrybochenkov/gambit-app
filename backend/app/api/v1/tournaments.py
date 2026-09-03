from typing import Annotated

from fastapi import APIRouter, Depends

from app.api import errors
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.tournaments import (
    PlayerTournamentListResponse,
    PlayerTournamentResponse,
)
from app.services.tournament_service import (
    TournamentCancellationUnavailableError,
    TournamentRegistrationAlreadyCheckedInError,
    TournamentRegistrationNotAllowedError,
    TournamentScheduleNotAllowedError,
    TournamentUnavailableError,
    tournament_service,
)

router = APIRouter(tags=["webapp"])


@router.get("/tournaments/week", response_model=PlayerTournamentListResponse)
async def get_current_week_tournaments(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlayerTournamentListResponse:
    try:
        tournaments = await tournament_service.get_current_week_tournaments_for_player(
            actor.telegram_id
        )
    except TournamentScheduleNotAllowedError as exc:
        raise errors.forbidden("Tournament schedule is unavailable") from exc
    return PlayerTournamentListResponse(
        items=[PlayerTournamentResponse.from_view(tournament) for tournament in tournaments]
    )


@router.get("/tournaments/{tournament_id}", response_model=PlayerTournamentResponse)
async def get_tournament_details(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlayerTournamentResponse:
    try:
        tournament = await tournament_service.get_current_week_tournament_for_player(
            actor.telegram_id,
            tournament_id,
        )
    except TournamentScheduleNotAllowedError as exc:
        raise errors.forbidden("Tournament schedule is unavailable") from exc
    except TournamentUnavailableError as exc:
        raise errors.not_found("Tournament is unavailable") from exc
    return PlayerTournamentResponse.from_view(tournament)


@router.get("/me/registrations", response_model=PlayerTournamentListResponse)
async def get_my_registrations(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlayerTournamentListResponse:
    try:
        tournaments = await tournament_service.get_current_week_registrations_for_player(
            actor.telegram_id
        )
    except TournamentRegistrationNotAllowedError as exc:
        raise errors.forbidden("Tournament registration is unavailable") from exc
    return PlayerTournamentListResponse(
        items=[PlayerTournamentResponse.from_view(tournament) for tournament in tournaments]
    )


@router.post(
    "/tournaments/{tournament_id}/registration",
    response_model=PlayerTournamentResponse,
)
async def register_for_tournament(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlayerTournamentResponse:
    try:
        await tournament_service.register_player_for_tournaments(
            actor.telegram_id,
            [tournament_id],
        )
        tournament = await tournament_service.get_current_week_tournament_for_player(
            actor.telegram_id,
            tournament_id,
        )
    except TournamentRegistrationNotAllowedError as exc:
        raise errors.forbidden("Tournament registration is unavailable") from exc
    except TournamentUnavailableError as exc:
        raise errors.conflict("Tournament is unavailable for registration") from exc
    return PlayerTournamentResponse.from_view(tournament)


@router.delete(
    "/tournaments/{tournament_id}/registration",
    response_model=PlayerTournamentResponse,
)
async def cancel_tournament_registration(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlayerTournamentResponse:
    try:
        await tournament_service.cancel_player_tournament_registrations(
            actor.telegram_id,
            [tournament_id],
        )
        tournament = await tournament_service.get_current_week_tournament_for_player(
            actor.telegram_id,
            tournament_id,
        )
    except TournamentRegistrationNotAllowedError as exc:
        raise errors.forbidden("Tournament registration is unavailable") from exc
    except TournamentCancellationUnavailableError as exc:
        raise errors.conflict("Tournament registration cannot be cancelled") from exc
    except TournamentRegistrationAlreadyCheckedInError as exc:
        raise errors.conflict("Tournament registration cannot be cancelled") from exc
    except TournamentUnavailableError as exc:
        raise errors.conflict("Tournament is unavailable") from exc
    return PlayerTournamentResponse.from_view(tournament)
