from pydantic import BaseModel, ConfigDict

from app.services.dto.registrations import (
    RegistrationCandidateView,
    RegistrationRequestView,
    RegistrationReviewOutcomeView,
    RegistrationReviewView,
)
from app.services.dto.users import UserView
from app.services.pagination import Page


class AdminRegistrationUserResponse(BaseModel):
    id: int
    display_name: str
    status: str
    role: str

    @classmethod
    def from_view(cls, view: UserView) -> "AdminRegistrationUserResponse":
        return cls(
            id=view.id,
            display_name=view.display_name,
            status=view.status.value,
            role=view.role.value,
        )


class AdminRegistrationRequestResponse(BaseModel):
    id: int
    request_type: str
    status: str
    requested_display_name: str | None
    requested_link_name: str | None
    candidate_user_id: int | None
    created_at: str

    @classmethod
    def from_view(cls, view: RegistrationRequestView) -> "AdminRegistrationRequestResponse":
        return cls(
            id=view.id,
            request_type=view.request_type,
            status=view.status,
            requested_display_name=view.requested_display_name,
            requested_link_name=view.requested_link_name,
            candidate_user_id=view.candidate_user_id,
            created_at=view.created_at,
        )


class AdminRegistrationCandidateResponse(BaseModel):
    user: AdminRegistrationUserResponse
    score: int
    reason: str

    @classmethod
    def from_view(cls, view: RegistrationCandidateView) -> "AdminRegistrationCandidateResponse":
        return cls(
            user=AdminRegistrationUserResponse.from_view(view.user),
            score=view.score,
            reason=view.reason,
        )


class AdminRegistrationReviewResponse(BaseModel):
    request: AdminRegistrationRequestResponse
    candidates: list[AdminRegistrationCandidateResponse]
    selected_candidate: AdminRegistrationCandidateResponse | None

    @classmethod
    def from_view(cls, view: RegistrationReviewView) -> "AdminRegistrationReviewResponse":
        return cls(
            request=AdminRegistrationRequestResponse.from_view(view.request),
            candidates=[
                AdminRegistrationCandidateResponse.from_view(item) for item in view.candidates
            ],
            selected_candidate=(
                AdminRegistrationCandidateResponse.from_view(view.selected_candidate)
                if view.selected_candidate is not None
                else None
            ),
        )


class AdminRegistrationReviewPageResponse(BaseModel):
    items: list[AdminRegistrationReviewResponse]
    page: int
    page_size: int
    total_items: int
    total_pages: int

    @classmethod
    def from_page(
        cls,
        page: Page[RegistrationReviewView],
    ) -> "AdminRegistrationReviewPageResponse":
        return cls(
            items=[AdminRegistrationReviewResponse.from_view(item) for item in page.items],
            page=page.page,
            page_size=page.page_size,
            total_items=page.total_items,
            total_pages=page.total_pages,
        )


class AdminRegistrationCandidateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_user_id: int


class AdminRegistrationApproveCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_user_id: int | None = None


class AdminRegistrationReviewOutcomeResponse(BaseModel):
    decision: str
    review: AdminRegistrationReviewResponse
    request: AdminRegistrationRequestResponse
    user: AdminRegistrationUserResponse | None
    reviewer: AdminRegistrationUserResponse

    @classmethod
    def from_view(
        cls,
        view: RegistrationReviewOutcomeView,
    ) -> "AdminRegistrationReviewOutcomeResponse":
        return cls(
            decision=view.decision.value,
            review=AdminRegistrationReviewResponse.from_view(view.review),
            request=AdminRegistrationRequestResponse.from_view(view.request),
            user=(AdminRegistrationUserResponse.from_view(view.user) if view.user else None),
            reviewer=AdminRegistrationUserResponse.from_view(view.reviewer),
        )
