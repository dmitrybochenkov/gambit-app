from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.api.v1.schemas.admin_tournaments import (
    AdminTournamentResponse,
    AdminTournamentResultsResponse,
)
from app.api.v1.schemas.rewards import PlayerRewardResponse
from app.db.models.enums import UserGender
from app.services.dto.check_in import (
    CheckedInPlayersView,
    CheckInCandidateView,
    CheckInGenderDecision,
    TournamentCheckInView,
)
from app.services.dto.results import (
    OpenTournamentPlayerDeleteResultView,
    TournamentResultsView,
)
from app.services.dto.users import UserView
from app.services.tournament_check_in_service import (
    CheckInResultView,
    CheckInRewardDecisionView,
)


class AdminCheckInCandidateResponse(BaseModel):
    user_id: int
    display_name: str
    is_pre_registered: bool
    is_checked_in: bool

    @classmethod
    def from_view(cls, view: CheckInCandidateView) -> "AdminCheckInCandidateResponse":
        return cls(
            user_id=view.user_id,
            display_name=view.display_name,
            is_pre_registered=view.is_pre_registered,
            is_checked_in=view.is_checked_in,
        )


class AdminCheckInResponse(BaseModel):
    tournament: AdminTournamentResponse
    registered_count: int
    registered_checked_in_count: int
    checked_in_count: int
    walk_in_count: int
    registered_candidates: list[AdminCheckInCandidateResponse]
    is_superadmin_late_override: bool

    @classmethod
    def from_view(cls, view: TournamentCheckInView) -> "AdminCheckInResponse":
        return cls(
            tournament=AdminTournamentResponse.from_view(view.tournament),
            registered_count=view.registered_count,
            registered_checked_in_count=view.registered_checked_in_count,
            checked_in_count=view.checked_in_count,
            walk_in_count=view.walk_in_count,
            registered_candidates=[
                AdminCheckInCandidateResponse.from_view(item)
                for item in view.registered_candidates or ()
            ],
            is_superadmin_late_override=view.is_superadmin_late_override,
        )


class AdminCheckedInPlayerResponse(BaseModel):
    display_name: str
    checked_in_at: datetime


class AdminCheckedInPlayersResponse(BaseModel):
    tournament: AdminTournamentResponse
    players: list[AdminCheckedInPlayerResponse]

    @classmethod
    def from_view(cls, view: CheckedInPlayersView) -> "AdminCheckedInPlayersResponse":
        return cls(
            tournament=AdminTournamentResponse.from_view(view.tournament),
            players=[
                AdminCheckedInPlayerResponse(
                    display_name=item.display_name,
                    checked_in_at=item.checked_in_at,
                )
                for item in view.players
            ],
        )


class AdminPlayerResponse(BaseModel):
    id: int
    display_name: str
    gender: UserGender | None

    @classmethod
    def from_view(cls, view: UserView) -> "AdminPlayerResponse":
        return cls(id=view.id, display_name=view.display_name, gender=view.gender)


class AdminPlayerListResponse(BaseModel):
    items: list[AdminPlayerResponse]


class AdminCheckInDecisionResponse(BaseModel):
    tournament: AdminTournamentResponse
    player: AdminPlayerResponse
    active_rewards: list[PlayerRewardResponse]

    @classmethod
    def from_view(cls, view: CheckInRewardDecisionView) -> "AdminCheckInDecisionResponse":
        return cls(
            tournament=AdminTournamentResponse.from_view(view.tournament),
            player=AdminPlayerResponse.from_view(view.user),
            active_rewards=[PlayerRewardResponse.from_view(item) for item in view.active_rewards],
        )


class AdminExistingPlayerCheckInRequest(BaseModel):
    kind: Literal["existing"]
    player_id: int
    gender_decision: CheckInGenderDecision
    reward_id: int | None = None


class AdminNewPlayerCheckInRequest(BaseModel):
    kind: Literal["new"]
    display_name: str
    gender: UserGender | None = None


AdminCheckInRequest = Annotated[
    AdminExistingPlayerCheckInRequest | AdminNewPlayerCheckInRequest,
    Field(discriminator="kind"),
]


class AdminCheckInResultResponse(BaseModel):
    tournament: AdminTournamentResponse
    player: AdminPlayerResponse
    created: bool

    @classmethod
    def from_view(cls, view: CheckInResultView) -> "AdminCheckInResultResponse":
        return cls(
            tournament=AdminTournamentResponse.from_view(view.tournament),
            player=AdminPlayerResponse.from_view(view.user),
            created=view.created,
        )


class AdminExistingParticipantRequest(BaseModel):
    kind: Literal["existing"]
    player_id: int


class AdminNewParticipantRequest(BaseModel):
    kind: Literal["new"]
    display_name: str


AdminParticipantCreateRequest = Annotated[
    AdminExistingParticipantRequest | AdminNewParticipantRequest,
    Field(discriminator="kind"),
]


class AdminParticipantDeleteResponse(BaseModel):
    tournament: AdminTournamentResponse
    player_id: int
    display_name: str
    deleted_registration: bool
    deleted_combinations_count: int

    @classmethod
    def from_view(
        cls,
        view: OpenTournamentPlayerDeleteResultView,
    ) -> "AdminParticipantDeleteResponse":
        return cls(
            tournament=AdminTournamentResponse.from_view(view.tournament),
            player_id=view.player.player_id,
            display_name=view.player.display_name,
            deleted_registration=view.deleted_registration,
            deleted_combinations_count=view.deleted_combinations_count,
        )


def participant_results_response(
    view: TournamentResultsView,
) -> AdminTournamentResultsResponse:
    return AdminTournamentResultsResponse.from_view(view)
