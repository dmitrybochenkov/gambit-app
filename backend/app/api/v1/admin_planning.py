from typing import Annotated, Never

from fastapi import APIRouter, Depends, Query

from app.api import errors
from app.api.business_notification_dependencies import tournament_cancellation_delivery
from app.api.dependencies import AuthenticatedActor, current_actor
from app.api.v1.schemas.admin_planning import (
    PlanningApprovalResponse,
    PlanningAutofillResponse,
    PlanningCalendarMonthResponse,
    PlanningCalendarWeekDetailResponse,
    PlanningCreatePreviewResponse,
    PlanningDeletePreviewResponse,
    PlanningDeleteResponse,
    PlanningFormatDetailResponse,
    PlanningTournamentCommand,
    PlanningTournamentResponse,
    PlanningTournamentTypeResponse,
    PlanningTypeChangeCommand,
    PlanningTypeChangeResponse,
    PlanningWeekCommand,
)
from app.services.access_policy import AdminAccessDeniedError
from app.services.business_notification_use_cases import (
    TournamentCancellationDelivery,
    TournamentPlanningUseCases,
)
from app.services.tournament_planning_service import (
    CalendarDefaultTournamentTypeNotFoundError,
    CalendarNoUnapprovedTournamentsError,
    CalendarTournamentDateAlreadyExistsError,
    CalendarTournamentNotEditableError,
    CalendarTournamentNotFoundError,
    CalendarTournamentTypeNotFoundError,
    CalendarWeeklyPlanIntegrityError,
    CalendarWeekNotEmptyError,
    tournament_planning_service,
)

router = APIRouter(prefix="/admin/planning", tags=["webapp-admin"])

PlanningError = (
    CalendarDefaultTournamentTypeNotFoundError
    | CalendarNoUnapprovedTournamentsError
    | CalendarTournamentDateAlreadyExistsError
    | CalendarTournamentNotEditableError
    | CalendarTournamentNotFoundError
    | CalendarTournamentTypeNotFoundError
    | CalendarWeekNotEmptyError
    | CalendarWeeklyPlanIntegrityError
)


def _raise_planning_error(exc: PlanningError) -> Never:
    if isinstance(exc, CalendarTournamentNotFoundError):
        raise errors.not_found("Tournament not found") from exc
    if isinstance(
        exc,
        (
            CalendarTournamentDateAlreadyExistsError,
            CalendarTournamentNotEditableError,
            CalendarWeekNotEmptyError,
            CalendarNoUnapprovedTournamentsError,
        ),
    ):
        raise errors.conflict("Tournament planning state conflict") from exc
    raise errors.validation_error("Invalid tournament planning request") from exc


@router.get("/calendar", response_model=PlanningCalendarMonthResponse)
async def get_calendar_month(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    year: Annotated[int | None, Query(ge=1)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> PlanningCalendarMonthResponse:
    try:
        view = await tournament_planning_service.get_calendar_month(
            actor.user_id,
            year=year,
            month=month,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    return PlanningCalendarMonthResponse.from_view(view)


@router.get("/calendar/week", response_model=PlanningCalendarWeekDetailResponse)
async def get_calendar_week(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    year: Annotated[int, Query(ge=1)],
    month: Annotated[int, Query(ge=1, le=12)],
    row_number: Annotated[int, Query(ge=1)],
) -> PlanningCalendarWeekDetailResponse:
    try:
        view = await tournament_planning_service.get_calendar_week(
            actor.user_id,
            year=year,
            month=month,
            row_number=row_number,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except CalendarWeeklyPlanIntegrityError as exc:
        _raise_planning_error(exc)
    return PlanningCalendarWeekDetailResponse.from_view(view)


@router.get("/tournament-types", response_model=list[PlanningTournamentTypeResponse])
async def list_tournament_types(
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> list[PlanningTournamentTypeResponse]:
    try:
        items = await tournament_planning_service.list_calendar_tournament_type_options(
            actor.user_id
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    return [PlanningTournamentTypeResponse.from_view(item) for item in items]


@router.get(
    "/tournament-types/{tournament_type_id}",
    response_model=PlanningFormatDetailResponse,
)
async def get_tournament_type_detail(
    tournament_type_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    year: Annotated[int, Query(ge=1)],
    month: Annotated[int, Query(ge=1, le=12)],
) -> PlanningFormatDetailResponse:
    try:
        view = await tournament_planning_service.get_calendar_format_detail(
            actor.user_id,
            year=year,
            month=month,
            tournament_type_id=tournament_type_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except CalendarTournamentTypeNotFoundError as exc:
        raise errors.not_found("Tournament type not found in calendar month") from exc
    return PlanningFormatDetailResponse.from_view(view)


@router.post("/tournaments/preview", response_model=PlanningCreatePreviewResponse)
async def preview_tournament_creation(
    request: PlanningTournamentCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningCreatePreviewResponse:
    try:
        view = await tournament_planning_service.get_calendar_create_preview(
            actor.user_id,
            tournament_date=request.tournament_date,
            tournament_type_id=request.tournament_type_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        CalendarTournamentDateAlreadyExistsError,
        CalendarTournamentTypeNotFoundError,
    ) as exc:
        _raise_planning_error(exc)
    return PlanningCreatePreviewResponse.from_view(view)


@router.post("/tournaments", response_model=PlanningTournamentResponse)
async def create_tournament(
    request: PlanningTournamentCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningTournamentResponse:
    try:
        view = await tournament_planning_service.create_calendar_tournament(
            actor.user_id,
            tournament_date=request.tournament_date,
            tournament_type_id=request.tournament_type_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        CalendarTournamentDateAlreadyExistsError,
        CalendarTournamentTypeNotFoundError,
        CalendarWeeklyPlanIntegrityError,
    ) as exc:
        _raise_planning_error(exc)
    return PlanningTournamentResponse.from_view(view)


@router.post("/weeks/autofill-preview", response_model=PlanningAutofillResponse)
async def preview_week_autofill(
    request: PlanningWeekCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningAutofillResponse:
    try:
        view = await tournament_planning_service.get_calendar_autofill_preview(
            actor.user_id,
            year=request.year,
            month=request.month,
            row_number=request.row_number,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarWeekNotEmptyError,
        CalendarWeeklyPlanIntegrityError,
    ) as exc:
        _raise_planning_error(exc)
    return PlanningAutofillResponse.from_view(view)


@router.post("/weeks/autofill", response_model=PlanningAutofillResponse)
async def autofill_week(
    request: PlanningWeekCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningAutofillResponse:
    try:
        view = await tournament_planning_service.create_calendar_autofill_week(
            actor.user_id,
            year=request.year,
            month=request.month,
            row_number=request.row_number,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        CalendarDefaultTournamentTypeNotFoundError,
        CalendarTournamentDateAlreadyExistsError,
        CalendarWeekNotEmptyError,
        CalendarWeeklyPlanIntegrityError,
    ) as exc:
        _raise_planning_error(exc)
    return PlanningAutofillResponse.from_view(view)


@router.post("/weeks/approval-preview", response_model=PlanningApprovalResponse)
async def preview_week_approval(
    request: PlanningWeekCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningApprovalResponse:
    try:
        view = await tournament_planning_service.get_week_approval_preview(
            actor.user_id,
            year=request.year,
            month=request.month,
            row_number=request.row_number,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (CalendarNoUnapprovedTournamentsError, CalendarWeeklyPlanIntegrityError) as exc:
        _raise_planning_error(exc)
    return PlanningApprovalResponse.from_view(view)


@router.post("/weeks/approve", response_model=PlanningApprovalResponse)
async def approve_week(
    request: PlanningWeekCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningApprovalResponse:
    try:
        view = await tournament_planning_service.approve_calendar_week(
            actor.user_id,
            year=request.year,
            month=request.month,
            row_number=request.row_number,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        CalendarNoUnapprovedTournamentsError,
        CalendarTournamentNotFoundError,
        CalendarWeeklyPlanIntegrityError,
    ) as exc:
        _raise_planning_error(exc)
    return PlanningApprovalResponse.from_view(view)


@router.post(
    "/tournaments/{tournament_id}/type-preview",
    response_model=PlanningTypeChangeResponse,
)
async def preview_tournament_type_change(
    tournament_id: int,
    request: PlanningTypeChangeCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningTypeChangeResponse:
    try:
        view = await tournament_planning_service.get_type_change_preview(
            actor.user_id,
            tournament_id=tournament_id,
            new_tournament_type_id=request.tournament_type_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        CalendarTournamentNotEditableError,
        CalendarTournamentNotFoundError,
        CalendarTournamentTypeNotFoundError,
    ) as exc:
        _raise_planning_error(exc)
    return PlanningTypeChangeResponse.from_view(view)


@router.patch("/tournaments/{tournament_id}/type", response_model=PlanningTournamentResponse)
async def change_tournament_type(
    tournament_id: int,
    request: PlanningTypeChangeCommand,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningTournamentResponse:
    try:
        view = await tournament_planning_service.change_calendar_tournament_type(
            actor.user_id,
            tournament_id=tournament_id,
            new_tournament_type_id=request.tournament_type_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (
        CalendarTournamentNotEditableError,
        CalendarTournamentNotFoundError,
        CalendarTournamentTypeNotFoundError,
    ) as exc:
        _raise_planning_error(exc)
    return PlanningTournamentResponse.from_view(view)


@router.get(
    "/tournaments/{tournament_id}/delete-preview",
    response_model=PlanningDeletePreviewResponse,
)
async def preview_tournament_delete(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
) -> PlanningDeletePreviewResponse:
    try:
        view = await tournament_planning_service.get_calendar_delete_preview(
            actor.user_id,
            tournament_id=tournament_id,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (CalendarTournamentNotEditableError, CalendarTournamentNotFoundError) as exc:
        _raise_planning_error(exc)
    return PlanningDeletePreviewResponse.from_view(view)


@router.delete("/tournaments/{tournament_id}", response_model=PlanningDeleteResponse)
async def delete_tournament(
    tournament_id: int,
    actor: Annotated[AuthenticatedActor, Depends(current_actor)],
    delivery: Annotated[
        TournamentCancellationDelivery,
        Depends(tournament_cancellation_delivery),
    ],
) -> PlanningDeleteResponse:
    try:
        tournament = await TournamentPlanningUseCases(
            tournament_planning_service
        ).delete_calendar_tournament(
            actor_user_id=actor.user_id,
            tournament_id=tournament_id,
            delivery=delivery,
        )
    except AdminAccessDeniedError as exc:
        raise errors.forbidden("Superadmin access required") from exc
    except (CalendarTournamentNotEditableError, CalendarTournamentNotFoundError) as exc:
        _raise_planning_error(exc)
    return PlanningDeleteResponse(
        tournament=PlanningTournamentResponse.from_view(tournament),
    )
