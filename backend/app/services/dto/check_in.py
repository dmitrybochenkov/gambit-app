from dataclasses import dataclass
from datetime import datetime

from app.services.dto.tournaments import TournamentView


@dataclass(frozen=True)
class CheckInCandidateView:
    user_id: int
    display_name: str
    is_pre_registered: bool
    is_checked_in: bool
    source: str | None = None
    has_result_data: bool = False


@dataclass(frozen=True)
class TournamentCheckInView:
    tournament: TournamentView
    registered_count: int
    registered_checked_in_count: int
    checked_in_count: int
    walk_in_count: int
    is_superadmin_late_override: bool = False


@dataclass(frozen=True)
class CheckedInPlayerView:
    display_name: str
    checked_in_at: datetime


@dataclass(frozen=True)
class CheckedInPlayersView:
    tournament: TournamentView
    players: list[CheckedInPlayerView]

    @property
    def total_count(self) -> int:
        return len(self.players)
