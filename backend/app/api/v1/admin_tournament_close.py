from typing import Annotated

from fastapi import APIRouter, Depends

from app.api import errors
from app.api.business_notification_dependencies import player_reward_notification_delivery
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.admin_tournament_close import (
    AdminClosePreviewResponse,
    AdminCloseReadinessResponse,
    AdminCorrectionDraft,
    AdminCorrectionDraftResponse,
    AdminCorrectionResultResponse,
    AdminTournamentCloseResponse,
    AdminTournamentFundRequest,
)
from app.api.v1.schemas.admin_tournaments import AdminTournamentResultsResponse
from app.services.access_policy import AdminAccessDeniedError
from app.services.business_notification_use_cases import (
    PlayerRewardNotificationDelivery,
    TournamentRewardUseCases,
)
from app.services.closed_tournament_correction_service import (
    closed_tournament_correction_service,
)
from app.services.result_errors import (
    ClosedTournamentCorrectionStaleError,
    FutureTournamentCannotBeClosedError,
    ResultInvalidFundError,
    ResultInvalidPlayerDataError,
    ResultPlayerAlreadyAddedError,
    ResultTournamentNotFoundError,
    ResultUserNotFoundError,
    ResultValidationError,
    TournamentResultsEditingUnavailableError,
)
from app.services.result_service import result_service

router = APIRouter(prefix="/admin/tournaments", tags=["webapp-admin"])


@router.get(
    "/{tournament_id}/close-readiness",
    response_model=AdminCloseReadinessResponse,
)
async def get_close_readiness(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminCloseReadinessResponse:
    try:
        view = await result_service.get_close_readiness(actor.user_id, tournament_id)
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except ResultTournamentNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except FutureTournamentCannotBeClosedError as exc:
        raise errors.conflict("Tournament cannot be closed yet") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament is not open for closing") from exc
    return AdminCloseReadinessResponse.from_view(view)


@router.post(
    "/{tournament_id}/close-preview",
    response_model=AdminClosePreviewResponse,
)
async def preview_tournament_close(
    tournament_id: int,
    request: AdminTournamentFundRequest,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminClosePreviewResponse:
    try:
        view = await result_service.preview_tournament_close(
            actor.user_id,
            tournament_id,
            request.tournament_fund,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except ResultTournamentNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except FutureTournamentCannotBeClosedError as exc:
        raise errors.conflict("Tournament cannot be closed yet") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament is not open for closing") from exc
    except ResultInvalidFundError as exc:
        raise errors.validation_error("Invalid tournament fund") from exc
    except ResultValidationError as exc:
        raise errors.validation_error("Tournament results are incomplete") from exc
    return AdminClosePreviewResponse(results=AdminTournamentResultsResponse.from_view(view))


@router.post(
    "/{tournament_id}/close",
    response_model=AdminTournamentCloseResponse,
)
async def close_tournament(
    tournament_id: int,
    request: AdminTournamentFundRequest,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    delivery: Annotated[
        PlayerRewardNotificationDelivery,
        Depends(player_reward_notification_delivery),
    ],
) -> AdminTournamentCloseResponse:
    try:
        view = await TournamentRewardUseCases(
            result_service,
            closed_tournament_correction_service,
        ).close_tournament(
            actor_user_id=actor.user_id,
            tournament_id=tournament_id,
            tournament_fund=request.tournament_fund,
            delivery=delivery,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except ResultTournamentNotFoundError as exc:
        raise errors.not_found("Tournament not found") from exc
    except FutureTournamentCannotBeClosedError as exc:
        raise errors.conflict("Tournament cannot be closed yet") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament is not open for closing") from exc
    except ResultInvalidFundError as exc:
        raise errors.validation_error("Invalid tournament fund") from exc
    except ResultValidationError as exc:
        raise errors.validation_error("Tournament results are incomplete") from exc
    return AdminTournamentCloseResponse.from_view(view)


@router.get(
    "/{tournament_id}/correction",
    response_model=AdminCorrectionDraftResponse,
)
async def begin_closed_tournament_correction(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminCorrectionDraftResponse:
    try:
        draft = await closed_tournament_correction_service.begin_closed_tournament_correction(
            actor.user_id,
            tournament_id,
        )
        results = await closed_tournament_correction_service.get_closed_tournament_draft_results(
            actor.user_id,
            draft,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except ResultTournamentNotFoundError as exc:
        raise errors.not_found("Closed tournament not found") from exc
    return AdminCorrectionDraftResponse(
        draft=AdminCorrectionDraft.from_view(draft),
        results=AdminTournamentResultsResponse.from_view(results),
    )


@router.post(
    "/{tournament_id}/correction-preview",
    response_model=AdminCorrectionResultResponse,
)
async def preview_closed_tournament_correction(
    tournament_id: int,
    request: AdminCorrectionDraft,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> AdminCorrectionResultResponse:
    draft = request.to_view()
    if draft.tournament_id != tournament_id:
        raise errors.validation_error("Correction tournament does not match route")
    try:
        view = (
            await closed_tournament_correction_service.build_closed_tournament_correction_preview(
                actor.user_id,
                draft,
            )
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (ResultTournamentNotFoundError, ResultUserNotFoundError) as exc:
        raise errors.not_found("Closed tournament or player not found") from exc
    except ClosedTournamentCorrectionStaleError as exc:
        raise errors.conflict("Correction draft is stale") from exc
    except ResultPlayerAlreadyAddedError as exc:
        raise errors.conflict("Player is already present in tournament") from exc
    except (ResultInvalidFundError, ResultInvalidPlayerDataError, ResultValidationError) as exc:
        raise errors.validation_error("Invalid tournament correction") from exc
    return AdminCorrectionResultResponse.from_view(view)


@router.post(
    "/{tournament_id}/correction",
    response_model=AdminCorrectionResultResponse,
)
async def apply_closed_tournament_correction(
    tournament_id: int,
    request: AdminCorrectionDraft,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    delivery: Annotated[
        PlayerRewardNotificationDelivery,
        Depends(player_reward_notification_delivery),
    ],
) -> AdminCorrectionResultResponse:
    draft = request.to_view()
    if draft.tournament_id != tournament_id:
        raise errors.validation_error("Correction tournament does not match route")
    try:
        view = await TournamentRewardUseCases(
            result_service,
            closed_tournament_correction_service,
        ).apply_closed_tournament_correction(
            actor_user_id=actor.user_id,
            draft=draft,
            delivery=delivery,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (ResultTournamentNotFoundError, ResultUserNotFoundError) as exc:
        raise errors.not_found("Closed tournament or player not found") from exc
    except ClosedTournamentCorrectionStaleError as exc:
        raise errors.conflict("Correction draft is stale") from exc
    except ResultPlayerAlreadyAddedError as exc:
        raise errors.conflict("Player is already present in tournament") from exc
    except (ResultInvalidFundError, ResultInvalidPlayerDataError, ResultValidationError) as exc:
        raise errors.validation_error("Invalid tournament correction") from exc
    except TournamentResultsEditingUnavailableError as exc:
        raise errors.conflict("Tournament correction is unavailable") from exc
    return AdminCorrectionResultResponse.from_view(view)
