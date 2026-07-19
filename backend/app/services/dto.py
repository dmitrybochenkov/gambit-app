from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class PlayerStatusView(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"


class PlayerRoleView(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


@dataclass(frozen=True)
class PlayerView:
    id: int
    telegram_id: int
    display_name: str
    full_name: str | None
    nickname: str | None
    status: PlayerStatusView
    role: PlayerRoleView

    @property
    def is_active(self) -> bool:
        return self.status == PlayerStatusView.ACTIVE

    @property
    def is_pending(self) -> bool:
        return self.status == PlayerStatusView.PENDING

    @property
    def is_blocked(self) -> bool:
        return self.status == PlayerStatusView.BLOCKED

    @property
    def is_admin(self) -> bool:
        return self.role in {PlayerRoleView.ADMIN, PlayerRoleView.SUPERADMIN}


@dataclass(frozen=True)
class RegistrationMatchView:
    score: int
    reason: str
    historical_player: PlayerView


@dataclass(frozen=True)
class RegistrationReviewView:
    player: PlayerView
    matches: list[RegistrationMatchView]


@dataclass(frozen=True)
class AdminPanelView:
    admin: PlayerView
    reviews: list[RegistrationReviewView]


@dataclass(frozen=True)
class RegistrationNotificationView:
    player: PlayerView
    admins: list[PlayerView]
    matches: list[RegistrationMatchView]


@dataclass(frozen=True)
class RegistrationReviewResultView:
    player: PlayerView
    admins: list[PlayerView]


@dataclass(frozen=True)
class TournamentView:
    id: int
    date: date
    tournament_type_id: int
    tournament_type_name: str | None


@dataclass(frozen=True)
class TournamentResultDraftPlayerView:
    player_id: int
    display_name: str
    place: int | None
    knockouts_count: int
    boss_knockouts_count: int


@dataclass(frozen=True)
class TournamentResultDraftView:
    tournament: TournamentView
    points_pool: Decimal | None
    players: list[TournamentResultDraftPlayerView]


@dataclass(frozen=True)
class AdminPromptView:
    id: int
    kind: str
    payload: str
    status: str


@dataclass(frozen=True)
class TournamentTypeOptionView:
    id: int
    name: str


@dataclass(frozen=True)
class PointsRatingView:
    player_id: int
    display_name: str
    total_points: Decimal
    tournaments_count: int


@dataclass(frozen=True)
class KnockoutsRatingView:
    player_id: int
    display_name: str
    knockouts_count: int
    boss_knockouts_count: int

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.boss_knockouts_count


@dataclass(frozen=True)
class RatingResultView:
    title: str
    rows: list[PointsRatingView] | list[KnockoutsRatingView]
    current_player_id: int


@dataclass(frozen=True)
class PlayerProfileView:
    display_name: str
    total_points: Decimal
    knockouts_count: int
    boss_knockouts_count: int
    tournaments_count: int
    first_places_count: int
    second_places_count: int
    third_places_count: int
    fourth_places_count: int
    fifth_places_count: int

    @property
    def total_knockouts_count(self) -> int:
        return self.knockouts_count + self.boss_knockouts_count
