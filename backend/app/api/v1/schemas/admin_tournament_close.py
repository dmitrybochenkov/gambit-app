from datetime import date

from pydantic import BaseModel

from app.api.v1.schemas.admin_tournaments import (
    AdminTournamentResponse,
    AdminTournamentResultsResponse,
)
from app.services.dto.results import (
    ClosedTournamentCorrectionDraftView,
    ClosedTournamentCorrectionResultView,
    TournamentCloseReadinessView,
    TournamentResultSnapshotItemView,
    TournamentResultsView,
)
from app.services.dto.rewards import (
    PlayerRewardCorrectionChangeView,
    PlayerRewardNotificationView,
)


class AdminTournamentFundRequest(BaseModel):
    tournament_fund: int


class AdminCloseReadinessResponse(BaseModel):
    tournament: AdminTournamentResponse
    is_ready: bool
    players_count: int
    photo_count: int
    has_photos: bool
    has_checkins: bool
    validation_errors: list[str]
    reasons: list[str]

    @classmethod
    def from_view(cls, view: TournamentCloseReadinessView) -> "AdminCloseReadinessResponse":
        return cls(
            tournament=AdminTournamentResponse.from_view(view.tournament),
            is_ready=view.is_ready,
            players_count=view.players_count,
            photo_count=view.photo_count,
            has_photos=view.has_photos,
            has_checkins=view.has_checkins,
            validation_errors=view.validation_errors,
            reasons=view.reasons,
        )


class AdminRewardNotificationResponse(BaseModel):
    reward_id: int
    player_id: int
    chips_amount: int
    source_place: int
    source_tournament_id: int
    source_tournament_date: date
    source_tournament_name: str
    valid_through: date

    @classmethod
    def from_view(cls, view: PlayerRewardNotificationView) -> "AdminRewardNotificationResponse":
        return cls(
            reward_id=view.reward_id,
            player_id=view.player_id,
            chips_amount=view.chips_amount,
            source_place=view.source_place,
            source_tournament_id=view.source_tournament_id,
            source_tournament_date=view.source_tournament_date,
            source_tournament_name=view.source_tournament_name,
            valid_through=view.valid_through,
        )


class AdminTournamentCloseResponse(BaseModel):
    results: AdminTournamentResultsResponse
    newly_issued_rewards: list[AdminRewardNotificationResponse]

    @classmethod
    def from_view(cls, view: TournamentResultsView) -> "AdminTournamentCloseResponse":
        return cls(
            results=AdminTournamentResultsResponse.from_view(view),
            newly_issued_rewards=[
                AdminRewardNotificationResponse.from_view(item)
                for item in view.newly_issued_rewards
            ],
        )


class AdminCorrectionSnapshotItem(BaseModel):
    result_id: int | None
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int

    @classmethod
    def from_view(cls, view: TournamentResultSnapshotItemView) -> "AdminCorrectionSnapshotItem":
        return cls(**view.__dict__)

    def to_view(self) -> TournamentResultSnapshotItemView:
        return TournamentResultSnapshotItemView(**self.model_dump())


class AdminCorrectionDraft(BaseModel):
    tournament_id: int
    original_tournament_fund: int | None
    proposed_tournament_fund: int | None
    original_results: list[AdminCorrectionSnapshotItem]
    proposed_results: list[AdminCorrectionSnapshotItem]

    @classmethod
    def from_view(cls, view: ClosedTournamentCorrectionDraftView) -> "AdminCorrectionDraft":
        return cls(
            tournament_id=view.tournament_id,
            original_tournament_fund=view.original_tournament_fund,
            proposed_tournament_fund=view.proposed_tournament_fund,
            original_results=[
                AdminCorrectionSnapshotItem.from_view(item) for item in view.original_results
            ],
            proposed_results=[
                AdminCorrectionSnapshotItem.from_view(item) for item in view.proposed_results
            ],
        )

    def to_view(self) -> ClosedTournamentCorrectionDraftView:
        return ClosedTournamentCorrectionDraftView(
            tournament_id=self.tournament_id,
            original_tournament_fund=self.original_tournament_fund,
            proposed_tournament_fund=self.proposed_tournament_fund,
            original_results=tuple(item.to_view() for item in self.original_results),
            proposed_results=tuple(item.to_view() for item in self.proposed_results),
        )


class AdminCorrectionDraftResponse(BaseModel):
    draft: AdminCorrectionDraft
    results: AdminTournamentResultsResponse


class AdminCorrectionFieldChangeResponse(BaseModel):
    label: str
    before: str
    after: str


class AdminCorrectionPlayerChangeResponse(BaseModel):
    player_id: int
    display_name: str
    fields: list[AdminCorrectionFieldChangeResponse]


class AdminRewardCorrectionChangeResponse(BaseModel):
    player_id: int
    display_name: str
    old_chips_amount: int | None
    new_chips_amount: int | None
    used: bool

    @classmethod
    def from_view(
        cls, view: PlayerRewardCorrectionChangeView
    ) -> "AdminRewardCorrectionChangeResponse":
        return cls(**view.__dict__)


class AdminCorrectionResultResponse(BaseModel):
    tournament_id: int
    tournament_date: date
    tournament_name: str
    result_changes: list[AdminCorrectionPlayerChangeResponse]
    reward_changes: list[AdminRewardCorrectionChangeResponse]
    used_reward_warnings: list[AdminRewardCorrectionChangeResponse]
    before_results: AdminTournamentResultsResponse | None
    after_results: AdminTournamentResultsResponse | None
    fund_before: int | None
    fund_after: int | None

    @classmethod
    def from_view(
        cls,
        view: ClosedTournamentCorrectionResultView,
    ) -> "AdminCorrectionResultResponse":
        before = view.before_results
        after = view.after_results
        return cls(
            tournament_id=view.tournament_id,
            tournament_date=view.tournament_date,
            tournament_name=view.tournament_name,
            result_changes=[
                AdminCorrectionPlayerChangeResponse(
                    player_id=item.player_id,
                    display_name=item.display_name,
                    fields=[
                        AdminCorrectionFieldChangeResponse(
                            label=field.label,
                            before=field.before,
                            after=field.after,
                        )
                        for field in item.fields
                    ],
                )
                for item in view.result_changes
            ],
            reward_changes=[
                AdminRewardCorrectionChangeResponse.from_view(item) for item in view.reward_changes
            ],
            used_reward_warnings=[
                AdminRewardCorrectionChangeResponse.from_view(item)
                for item in view.used_reward_warnings
            ],
            before_results=(
                AdminTournamentResultsResponse.from_view(before)
                if isinstance(before, TournamentResultsView)
                else None
            ),
            after_results=(
                AdminTournamentResultsResponse.from_view(after)
                if isinstance(after, TournamentResultsView)
                else None
            ),
            fund_before=view.fund_before,
            fund_after=view.fund_after,
        )


class AdminClosePreviewResponse(BaseModel):
    results: AdminTournamentResultsResponse
