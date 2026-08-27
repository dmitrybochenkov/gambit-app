from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.dto.rewards import (
    PlayerRewardCorrectionChangeView,
    PlayerRewardCorrectionNotificationView,
    PlayerRewardNotificationView,
)
from app.services.dto.tournaments import TournamentScheduleDetailsView, TournamentView


@dataclass(frozen=True)
class TournamentResultPlayerView:
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int = 0
    tournament_points: Decimal = Decimal("0")
    knockout_points: Decimal = Decimal("0")

    @property
    def total_points(self) -> Decimal:
        return self.tournament_points + self.knockout_points + Decimal(self.bonus_points)


@dataclass(frozen=True)
class OpenTournamentPlayerDeletePreviewView:
    tournament: TournamentView
    player: TournamentResultPlayerView
    combinations_count: int


@dataclass(frozen=True)
class OpenTournamentPlayerDeleteResultView:
    tournament: TournamentView
    player: TournamentResultPlayerView
    deleted_registration: bool
    deleted_combinations_count: int


@dataclass(frozen=True)
class TournamentResultSnapshotItemView:
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    big_knockouts_count: int
    bonus_points: int


@dataclass(frozen=True)
class ClosedTournamentCorrectionDraftView:
    tournament_id: int
    original_results: tuple[TournamentResultSnapshotItemView, ...]
    proposed_results: tuple[TournamentResultSnapshotItemView, ...]


@dataclass(frozen=True)
class TournamentResultFieldChangeView:
    label: str
    before: str
    after: str


@dataclass(frozen=True)
class TournamentResultPlayerChangeView:
    player_id: int
    display_name: str
    fields: tuple[TournamentResultFieldChangeView, ...]


@dataclass(frozen=True)
class ClosedTournamentCorrectionResultView:
    tournament_id: int
    tournament_date: date
    tournament_name: str
    result_changes: tuple[TournamentResultPlayerChangeView, ...]
    reward_changes: tuple[PlayerRewardCorrectionChangeView, ...]
    used_reward_warnings: tuple[PlayerRewardCorrectionChangeView, ...]
    player_notifications: tuple[PlayerRewardCorrectionNotificationView, ...]


@dataclass(frozen=True)
class TournamentResultsView:
    tournament: TournamentView
    tournament_fund: int | None
    players: list[TournamentResultPlayerView]
    knockout_mode: str = "none"
    supports_bonus_points: bool = False
    photo_count: int = 0
    newly_issued_rewards: tuple[PlayerRewardNotificationView, ...] = ()

    @property
    def entered_players(self) -> list[TournamentResultPlayerView]:
        return [player for player in self.players if self.has_entered_result(player)]

    def has_entered_result(self, player: TournamentResultPlayerView) -> bool:
        if player.place is not None:
            return True
        if self.knockout_mode in {"small", "small_big"} and player.knockouts_count > 0:
            return True
        if self.knockout_mode == "small_big" and player.big_knockouts_count > 0:
            return True
        return self.supports_bonus_points and player.bonus_points > 0

    @property
    def required_places(self) -> tuple[int, ...]:
        return tuple(range(1, min(5, len(self.players)) + 1))

    @property
    def bonus_points_label(self) -> str:
        if self.tournament.tournament_type_code == "mystery_bounty":
            return "Доп. очки"
        return "Бонус"


@dataclass(frozen=True)
class TournamentPhotoView:
    id: int
    tournament_id: int
    telegram_file_id: str
    telegram_file_unique_id: str
    position: int


@dataclass(frozen=True)
class TournamentPhotoAddView:
    tournament_id: int
    photo_count: int
    created: bool
    limit_reached: bool = False


@dataclass(frozen=True)
class TournamentCombinationView:
    id: int
    tournament_id: int
    player_id: int
    display_name: str
    combination_type: str
    rank: str | None = None


@dataclass(frozen=True)
class TournamentCombinationPlayerView:
    player_id: int
    display_name: str


@dataclass(frozen=True)
class TournamentCombinationsView:
    tournament: TournamentView
    combinations: list[TournamentCombinationView]
    players: list[TournamentCombinationPlayerView]


@dataclass(frozen=True)
class TournamentPublicationDestinationView:
    destination_type: str
    chat_id: int
    already_published: bool


@dataclass(frozen=True)
class TournamentPublicationPlaceView:
    place: int
    display_name: str
    total_points: Decimal


@dataclass(frozen=True)
class TournamentPublicationKnockoutView:
    display_name: str
    knockouts_count: int
    big_knockouts_count: int


@dataclass(frozen=True)
class TournamentResultPublicationView:
    tournament: TournamentView
    tournament_fund: int
    places: list[TournamentPublicationPlaceView]
    top_knockouters: list[TournamentPublicationKnockoutView]
    combinations: list[TournamentCombinationView]
    photos: list[TournamentPhotoView]
    destinations: list[TournamentPublicationDestinationView]
    content_hash: str


@dataclass(frozen=True)
class SchedulePublicationView:
    tournaments: list[TournamentScheduleDetailsView]
    destinations: list[TournamentPublicationDestinationView]
    content_hash: str


@dataclass(frozen=True)
class TournamentPublicationResultView:
    destination_type: str
    sent: bool
    already_published: bool = False
    failed: bool = False


@dataclass(frozen=True)
class TournamentPublicationSummaryView:
    results: list[TournamentPublicationResultView]

    @property
    def has_failures(self) -> bool:
        return any(item.failed for item in self.results)

    @property
    def has_sent(self) -> bool:
        return any(item.sent for item in self.results)


@dataclass(frozen=True)
class TournamentCloseReadinessView:
    tournament: TournamentView
    is_ready: bool
    photo_count: int
    has_photos: bool
    has_checkins: bool
    validation_errors: list[str]
    reasons: list[str]
    players_count: int = 0
